"""LLM Provider Registry with circuit breaker pattern + token tracking.

Phase 1: Full Provider Registry + circuit breaker (spec requirements).
Phase 2: Token tracking (OpenClaw SessionEntry pattern).

Borrows from:
- nanobot Provider Registry: keyword-based provider matching, easy addition
- openakita Brain: thin wrapper, progressive cooldown, health management
- circuitbreaker pattern: automatic fallback on provider failure
- OpenClaw SessionEntry: token tracking per call
"""

import json
import time
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

from config import settings

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when AI features are used without a configured real provider."""

# Progressive cooldown steps (borrowed from openakita)
COOLDOWN_STEPS = [5, 10, 20, 60]

# Circuit breaker thresholds
CIRCUIT_OPEN_THRESHOLD = 3  # failures before opening circuit
CIRCUIT_RESET_TIMEOUT = 120  # seconds before trying again


class LLMClient(ABC):
    """Base LLM client (openakita LLMProvider pattern).

    Token tracking (OpenClaw SessionEntry pattern):
    - chat() and extract() return tuple[str, dict] with usage info
    - stream_chat() stores usage in _last_usage, accessible via get_last_usage()
    """

    provider_name: str = "base"

    def __init__(self):
        self._healthy = True
        self._cooldown_until: float = 0
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False
        self._circuit_open_time: float = 0
        self._last_usage: dict = {}

    def get_last_usage(self) -> dict:
        """Get token usage from the last API call (useful after streaming)."""
        return self._last_usage

    @property
    def is_healthy(self) -> bool:
        # Circuit breaker: auto-reset after timeout
        if self._circuit_open:
            if time.time() - self._circuit_open_time >= CIRCUIT_RESET_TIMEOUT:
                self._circuit_open = False
                self._healthy = True
                self._consecutive_failures = 0
                logger.info(f"Circuit breaker reset for {self.provider_name}")
            else:
                return False

        if self._cooldown_until > 0 and time.time() >= self._cooldown_until:
            self._healthy = True
            self._cooldown_until = 0
        return self._healthy

    def mark_unhealthy(self, error: str):
        """Progressive cooldown + circuit breaker (openakita + circuitbreaker pattern)."""
        self._healthy = False
        self._consecutive_failures += 1

        # Circuit breaker: open after threshold
        if self._consecutive_failures >= CIRCUIT_OPEN_THRESHOLD:
            self._circuit_open = True
            self._circuit_open_time = time.time()
            logger.error(
                f"Circuit OPEN for {self.provider_name} after "
                f"{self._consecutive_failures} failures: {error}"
            )
            return

        idx = min(self._consecutive_failures - 1, len(COOLDOWN_STEPS) - 1)
        cooldown = COOLDOWN_STEPS[idx]
        self._cooldown_until = time.time() + cooldown
        logger.warning(f"LLM {self.provider_name} unhealthy: {error}, cooldown {cooldown}s")

    def mark_healthy(self):
        self._healthy = True
        self._consecutive_failures = 0
        self._cooldown_until = 0
        self._circuit_open = False

    async def ping(self) -> bool:
        """Active liveness check. Override for providers that need probing."""
        return self.is_healthy

    @abstractmethod
    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        """Stream chat response chunks. Token usage stored in _last_usage.

        images: optional list of {"data": base64_str, "media_type": "image/png"|...}
        """
        ...

    @abstractmethod
    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        """Non-streaming chat response. Returns (content, usage_dict).

        images: optional list of {"data": base64_str, "media_type": "image/png"|...}
        """
        ...

    @abstractmethod
    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        """Lightweight extraction call. Returns (content, usage_dict)."""
        ...


def _build_openai_user_content(text: str, images: list[dict] | None = None) -> str | list[dict]:
    """Build OpenAI user content with optional vision image blocks."""
    if not images:
        return text
    content: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        data_uri = f"data:{img.get('media_type', 'image/png')};base64,{img['data']}"
        content.append({"type": "image_url", "image_url": {"url": data_uri, "detail": "auto"}})
    return content


def _build_anthropic_user_content(text: str, images: list[dict] | None = None) -> str | list[dict]:
    """Build Anthropic user content with optional vision image blocks."""
    if not images:
        return text
    content: list[dict] = []
    for img in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img.get("media_type", "image/png"), "data": img["data"]},
        })
    content.append({"type": "text", "text": text})
    return content


class OpenAIClient(LLMClient):
    """OpenAI-compatible LLM client."""

    provider_name = "openai"

    # Local backends that may not support stream_options
    _NO_STREAM_OPTIONS = {"ollama", "vllm", "lmstudio", "textgenwebui", "custom"}

    def __init__(self, api_key: str, model: str, base_url: str | None = None, name: str = "openai"):
        super().__init__()
        import httpx
        from openai import AsyncOpenAI

        self.provider_name = name
        self._supports_stream_options = name not in self._NO_STREAM_OPTIONS
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        # Timeout: 10s connect, 120s read (streaming), 30s write, 10s pool
        kwargs["timeout"] = httpx.Timeout(connect=10, read=120, write=30, pool=10)
        self.client = AsyncOpenAI(**kwargs)
        self.model = model

    async def ping(self) -> bool:
        """Active liveness probe for local backends (OpenClaw pattern).

        Classifies errors: unreachable / auth / rate_limit / timeout / server_error.
        """
        if self.provider_name not in self._NO_STREAM_OPTIONS:
            return self.is_healthy  # Cloud APIs: trust cached status
        try:
            import httpx
            base = str(self.client.base_url).rstrip("/")
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(f"{base}/models")
            if resp.status_code < 400:
                self.mark_healthy()
                return True
            if resp.status_code in (401, 403):
                self.mark_unhealthy(f"auth_error ({resp.status_code})")
            elif resp.status_code == 429:
                self.mark_unhealthy("rate_limited")
            elif resp.status_code >= 500:
                self.mark_unhealthy(f"server_error ({resp.status_code})")
            else:
                self.mark_unhealthy(f"unexpected_status ({resp.status_code})")
            return False
        except Exception as e:
            ename = type(e).__name__
            if "Connect" in ename or "ConnectionRefused" in str(e):
                self.mark_unhealthy("unreachable")
            elif "Timeout" in ename:
                self.mark_unhealthy("timeout")
            else:
                self.mark_unhealthy(f"probe_error: {e}")
            return False

    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        try:
            user_content = _build_openai_user_content(user_message, images)
            create_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "stream": True,
            }
            if self._supports_stream_options:
                create_kwargs["stream_options"] = {"include_usage": True}
            stream = await self.client.chat.completions.create(**create_kwargs)
            marked_healthy = False
            async for chunk in stream:
                if chunk.usage:
                    self._last_usage = {
                        "input_tokens": chunk.usage.prompt_tokens or 0,
                        "output_tokens": chunk.usage.completion_tokens or 0,
                    }
                if chunk.choices and chunk.choices[0].delta.content:
                    if not marked_healthy:
                        self.mark_healthy()
                        marked_healthy = True
                    yield chunk.choices[0].delta.content
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        try:
            user_content = _build_openai_user_content(user_message, images)
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            self.mark_healthy()
            usage = {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return response.choices[0].message.content or "", usage
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> tuple[str, list[dict], dict]:
        """Chat with OpenAI native function calling.

        Args:
            messages: Full conversation history (system, user, assistant, tool).
            tools: OpenAI function calling schemas.

        Returns:
            (text_response, tool_calls, usage_dict)
            tool_calls: [{"id": str, "name": str, "arguments": dict}, ...]
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
            self.mark_healthy()
            msg = response.choices[0].message
            text = msg.content or ""
            tool_calls: list[dict[str, Any]] = []
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {"raw": tc.function.arguments}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })
            usage = {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return text, tool_calls, usage
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        """Lightweight extraction (openakita's think_lightweight pattern)."""
        return await self.chat(system_prompt, user_message)


class AnthropicClient(LLMClient):
    """Anthropic Claude client."""

    provider_name = "anthropic"

    def __init__(self, api_key: str, model: str):
        super().__init__()
        import httpx
        from anthropic import AsyncAnthropic

        # Timeout: 10s connect, 120s read (streaming), 30s write, 10s pool
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10),
        )
        self.model = model

    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        try:
            user_content = _build_anthropic_user_content(user_message, images)
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                marked_healthy = False
                async for text in stream.text_stream:
                    if not marked_healthy:
                        self.mark_healthy()
                        marked_healthy = True
                    yield text
                # Capture usage after stream completes
                final = await stream.get_final_message()
                self._last_usage = {
                    "input_tokens": final.usage.input_tokens if final.usage else 0,
                    "output_tokens": final.usage.output_tokens if final.usage else 0,
                }
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        try:
            user_content = _build_anthropic_user_content(user_message, images)
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            self.mark_healthy()
            usage = {
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return response.content[0].text, usage
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> tuple[str, list[dict], dict]:
        """Chat with Anthropic tool_use support.

        Converts OpenAI-format tool schemas to Anthropic format, calls the API,
        and normalizes the response back to the common format.
        """
        # Convert OpenAI tool schema → Anthropic format
        anthropic_tools = []
        for t in tools:
            func = t.get("function", t)
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })

        # Extract system prompt from messages (Anthropic uses separate system param)
        system_prompt = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg.get("content", "")
            elif msg["role"] == "tool":
                # Anthropic expects tool_result blocks
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                # Convert assistant tool_calls to Anthropic format
                content_blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    func = tc.get("function", tc)
                    try:
                        args = json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"]
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Malformed tool call arguments for %s, using empty dict", func.get("name", "?"))
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func["name"],
                        "input": args,
                    })
                api_messages.append({"role": "assistant", "content": content_blocks})
            else:
                api_messages.append(msg)

        # Anthropic requires alternating user/assistant roles.
        # Merge consecutive same-role messages (e.g., multiple tool_results → one user msg)
        merged_messages: list[dict] = []
        for msg in api_messages:
            if merged_messages and merged_messages[-1]["role"] == msg["role"]:
                prev = merged_messages[-1]
                # Merge content: ensure both are lists, then concatenate
                prev_content = prev["content"] if isinstance(prev["content"], list) else [{"type": "text", "text": prev["content"]}]
                new_content = msg["content"] if isinstance(msg["content"], list) else [{"type": "text", "text": msg["content"]}]
                prev["content"] = prev_content + new_content
            else:
                merged_messages.append({**msg})

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=merged_messages,
                tools=anthropic_tools,
            )
            self.mark_healthy()

            text = ""
            tool_calls: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "text":
                    text += block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input,
                    })

            usage = {
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return text, tool_calls, usage
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        return await self.chat(system_prompt, user_message)


class MockLLMClient(LLMClient):
    """Fallback local client when no external API key is configured."""

    provider_name = "mock"

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate for mock tracking."""
        return max(1, len(text) // 4)

    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        self.mark_healthy()
        img_note = f" (with {len(images)} image(s))" if images else ""
        content = (
            "No LLM API key configured. This is a local fallback response. "
            f"Your message was: {user_message}{img_note}"
        )
        self._last_usage = {
            "input_tokens": self._estimate_tokens(system_prompt + user_message),
            "output_tokens": self._estimate_tokens(content),
        }
        yield content

    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        self.mark_healthy()
        img_note = f" (with {len(images)} image(s))" if images else ""
        content = (
            "No LLM API key configured. This is a local fallback response. "
            f"Your message was: {user_message}{img_note}"
        )
        usage = {
            "input_tokens": self._estimate_tokens(system_prompt + user_message),
            "output_tokens": self._estimate_tokens(content),
        }
        self._last_usage = usage
        return content, usage

    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        self.mark_healthy()
        usage = {
            "input_tokens": self._estimate_tokens(system_prompt + user_message),
            "output_tokens": 1,
        }
        self._last_usage = usage
        return "NONE", usage


# ──────────────────────────────────────────────────────────────
# Provider Registry (nanobot pattern)
# ──────────────────────────────────────────────────────────────

class ProviderRegistry:
    """Registry of LLM providers with automatic fallback.

    Borrowed from nanobot: keyword-based registration + easy extension.
    Added: circuit breaker fallback chain.
    """

    def __init__(self):
        self._providers: dict[str, LLMClient] = {}
        self._primary: str | None = None
        self._fallback_order: list[str] = []
        self._model_variants: dict[str, LLMClient] = {}
        # Background health monitor (OpenClaw pattern)
        self._probe_cache: dict[str, dict] = {}
        self._probe_task: object | None = None  # asyncio.Task

    def register(self, name: str, client: LLMClient, primary: bool = False):
        """Register a provider."""
        self._providers[name] = client
        if primary:
            self._primary = name
        if name not in self._fallback_order:
            self._fallback_order.append(name)

    def register_variant(self, hint: str, client: LLMClient):
        """Register a model variant for size hints (large/small/fast)."""
        self._model_variants[hint] = client

    def get(self, name: str | None = None) -> LLMClient:
        """Get a healthy provider, with automatic fallback.

        Args:
            name: Provider name (e.g. "openai"), model preference hint
                  ("large"/"small"/"fast"), or None for default.

        Fallback chain: model_variants → primary → fallback_order.
        """
        if not self._providers:
            raise LLMConfigurationError(
                "No LLM provider is configured. Set an API key or local LLM backend before using AI features."
            )

        # Check model_preference hints (large/small/fast) first
        if name and name in self._model_variants:
            client = self._model_variants[name]
            if client.is_healthy:
                return client
            # If variant is unhealthy, fall through to primary/fallback

        # Translate unknown names to None for fallback
        if name and name not in self._providers:
            name = None  # Fall through to primary/fallback chain

        # Try requested provider first
        if name and name in self._providers:
            client = self._providers[name]
            if client.is_healthy:
                return client

        # Try primary
        if self._primary and self._primary in self._providers:
            client = self._providers[self._primary]
            if client.is_healthy:
                return client

        # Fallback chain
        for provider_name in self._fallback_order:
            client = self._providers[provider_name]
            if client.is_healthy:
                logger.info(f"Falling back to {provider_name}")
                return client

        raise RuntimeError("All LLM providers are unhealthy. Please check API keys and network.")

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    @property
    def primary_name(self) -> str | None:
        """Name of the primary provider (public accessor)."""
        return self._primary

    async def ping_all(self) -> dict[str, bool]:
        """Actively probe all providers and return live health status."""
        import asyncio
        results = await asyncio.gather(
            *(client.ping() for client in self._providers.values()),
            return_exceptions=True,
        )
        return {
            name: (r is True)
            for (name, _), r in zip(self._providers.items(), results)
        }

    # ── Background health monitor (OpenClaw pattern) ──────────

    def start_health_monitor(self, interval: float = 30.0):
        """Start background health probe loop. Call once at app startup."""
        import asyncio
        if self._probe_task is not None:
            return

        async def _loop():
            while True:
                await self._refresh_probe_cache()
                await asyncio.sleep(interval)

        self._probe_task = asyncio.create_task(_loop())
        logger.info("Health monitor started (interval=%ss)", interval)

    async def stop_health_monitor(self):
        """Cancel background probe loop on shutdown."""
        import asyncio
        task = self._probe_task
        if task is not None and isinstance(task, asyncio.Task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._probe_task = None

    async def _refresh_probe_cache(self):
        """Probe every provider, store detailed results in cache."""
        import asyncio
        items = list(self._providers.items())
        results = await asyncio.gather(
            *(self._probe_one(name, client) for name, client in items),
            return_exceptions=True,
        )
        for (name, _), result in zip(items, results):
            if isinstance(result, dict):
                self._probe_cache[name] = result
            else:
                self._probe_cache[name] = {
                    "healthy": False,
                    "status": "error",
                    "error": str(result),
                    "latency_ms": 0,
                    "checked_at": time.time(),
                }

    async def _probe_one(self, name: str, client: LLMClient) -> dict:
        start = time.time()
        try:
            healthy = await client.ping()
            elapsed = (time.time() - start) * 1000
            return {
                "healthy": healthy,
                "status": "ok" if healthy else "unhealthy",
                "error": None if healthy else getattr(client, '_last_error', None),
                "latency_ms": round(elapsed, 1),
                "checked_at": time.time(),
            }
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            return {
                "healthy": False,
                "status": "error",
                "error": str(e),
                "latency_ms": round(elapsed, 1),
                "checked_at": time.time(),
            }

    @property
    def provider_health_cached(self) -> dict[str, dict]:
        """Cached probe details per provider (OpenClaw pattern)."""
        return dict(self._probe_cache)

    @property
    def provider_health(self) -> dict[str, bool]:
        """Health status of all registered providers (public accessor)."""
        if self._probe_cache:
            return {name: d["healthy"] for name, d in self._probe_cache.items()}
        return {name: client.is_healthy for name, client in self._providers.items()}


# ──────────────────────────────────────────────────────────────
# Global singleton (nanobot pattern: create once, reuse)
# ──────────────────────────────────────────────────────────────

_registry: ProviderRegistry | None = None


def _register_variant(registry: ProviderRegistry, provider: str, variant_model: str, hint: str):
    """Create a variant client using the same provider but a different model."""
    primary_client = registry._providers.get(provider)
    if primary_client is None:
        return
    if isinstance(primary_client, OpenAIClient):
        variant = OpenAIClient(
            primary_client.client.api_key,
            variant_model,
            base_url=str(primary_client.client.base_url) if primary_client.client.base_url else None,
            name=f"{provider}-{hint}",
        )
        registry.register_variant(hint, variant)
    elif isinstance(primary_client, AnthropicClient):
        variant = AnthropicClient(primary_client.client.api_key, variant_model)
        registry.register_variant(hint, variant)


# ── Declarative provider definitions ─────────────────────────
# Each entry: (name, settings_key_attr, base_url, default_model, model_prefixes)
_OPENAI_COMPAT_PROVIDERS = [
    ("openai",     "openai_api_key",     None,                                                           "gpt-4o-mini",              ("gpt-", "o1-", "o3-", "o4-")),
    ("deepseek",   "deepseek_api_key",   "https://api.deepseek.com/v1",                                  "deepseek-chat",            ("deepseek-",)),
    ("openrouter", "openrouter_api_key", "https://openrouter.ai/api/v1",                                 "openai/gpt-4o-mini",       ()),
    ("gemini",     "gemini_api_key",     "https://generativelanguage.googleapis.com/v1beta/openai/",     "gemini-2.0-flash",         ("gemini-",)),
    ("groq",       "groq_api_key",       "https://api.groq.com/openai/v1",                               "llama-3.3-70b-versatile",  ("llama-", "mixtral-", "gemma-")),
]

_LOCAL_PROVIDERS = [
    # (name, dummy_api_key, base_url_attr)
    ("vllm",          "none",       "vllm_base_url"),
    ("lmstudio",      "lm-studio",  "lmstudio_base_url"),
    ("textgenwebui",  "none",       "textgenwebui_base_url"),
]


def _resolve_model(user_model: str, default_model: str, prefixes: tuple[str, ...]) -> str:
    """Pick provider-appropriate model: use user_model if it matches prefixes, else default."""
    if not prefixes:
        return default_model
    if any(user_model.lower().startswith(p) for p in prefixes):
        return user_model
    return default_model


def _build_registry() -> ProviderRegistry:
    """Build the provider registry from env vars."""
    registry = ProviderRegistry()
    provider = settings.llm_provider.lower()
    model = settings.llm_model

    # --- OpenAI-compatible cloud providers ---
    for name, key_attr, base_url, default_model, prefixes in _OPENAI_COMPAT_PROVIDERS:
        api_key = getattr(settings, key_attr, None)
        if not api_key:
            continue
        pmodel = model if provider == name else _resolve_model(model, default_model, prefixes)
        client = OpenAIClient(api_key, pmodel, base_url=base_url, name=name)
        registry.register(name, client, primary=(provider == name))

    # --- Anthropic (separate client class) ---
    if settings.anthropic_api_key:
        amodel = model if provider == "anthropic" else (
            model if model.lower().startswith("claude-") else "claude-sonnet-4-20250514"
        )
        client = AnthropicClient(settings.anthropic_api_key, amodel)
        registry.register("anthropic", client, primary=(provider == "anthropic"))

    # --- Ollama (opt-in local provider) ---
    if provider == "ollama":
        ollama_model = model or "llama3.2:3b"
        ollama_client = OpenAIClient(
            "ollama",
            ollama_model,
            base_url=f"{settings.ollama_base_url}/v1",
            name="ollama",
        )
        registry.register("ollama", ollama_client, primary=True)

    # --- Local inference backends (only when selected) ---
    for name, dummy_key, base_url_attr in _LOCAL_PROVIDERS:
        if provider == name:
            client = OpenAIClient(dummy_key, model, base_url=getattr(settings, base_url_attr), name=name)
            registry.register(name, client, primary=True)

    # --- Generic OpenAI-compatible endpoint ---
    if settings.custom_llm_base_url:
        client = OpenAIClient(
            settings.custom_llm_api_key or "none",
            settings.custom_llm_model or model,
            base_url=settings.custom_llm_base_url, name="custom",
        )
        registry.register("custom", client, primary=(provider == "custom"))

    # --- LiteLLM (opt-in universal adapter) ---
    if settings.use_litellm and settings.litellm_model:
        try:
            from services.llm.litellm_client import LiteLLMClient
            client = LiteLLMClient(
                model=settings.litellm_model,
                api_base=settings.litellm_api_base or None,
                api_key=settings.litellm_api_key or None,
            )
            registry.register("litellm", client, primary=True)
            logger.info("LiteLLM provider registered with model: %s", settings.litellm_model)
        except ImportError:
            logger.warning("LiteLLM requested but not installed. Run: pip install litellm")
        except Exception as e:
            logger.warning("LiteLLM registration failed: %s", e)

    # --- Model size variants (agent preference routing) ---
    for attr, hint in [("llm_model_large", "large"), ("llm_model_small", "small"),
                       ("llm_model_fast", "fast"), ("llm_model_standard", "standard"),
                       ("llm_model_frontier", "frontier")]:
        variant_model = getattr(settings, attr, None)
        if variant_model and variant_model != model:
            _register_variant(registry, provider, variant_model, hint)
    # Alias fallbacks: fast↔small, frontier↔large
    if "fast" not in registry._model_variants and "small" in registry._model_variants:
        registry.register_variant("fast", registry._model_variants["small"])
    if "frontier" not in registry._model_variants and "large" in registry._model_variants:
        registry.register_variant("frontier", registry._model_variants["large"])

    # --- Mock fallback ---
    if not registry.available_providers:
        if settings.llm_required:
            logger.error(
                "No LLM provider configured while LLM_REQUIRED is enabled. "
                "AI endpoints will fail until a real provider is configured."
            )
        else:
            logger.warning(
                "No LLM provider available; using mock fallback. "
                "Install Ollama (https://ollama.com) for local AI, or set an API key "
                "(OPENAI_API_KEY / ANTHROPIC_API_KEY / etc.) for cloud providers."
            )
            registry.register("mock", MockLLMClient(), primary=True)

    return registry


def get_llm_client(provider: str | None = None) -> LLMClient:
    """Get or create LLM client from the Provider Registry.

    With circuit breaker fallback: if primary is down, automatically
    tries the next available provider.
    """
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry.get(provider)


def get_registry() -> ProviderRegistry:
    """Get the global provider registry."""
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry
