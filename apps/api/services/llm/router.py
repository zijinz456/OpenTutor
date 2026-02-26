"""LLM Provider Registry with circuit breaker pattern.

Phase 1: Full Provider Registry + circuit breaker (spec requirements).

Borrows from:
- nanobot Provider Registry: keyword-based provider matching, easy addition
- openakita Brain: thin wrapper, progressive cooldown, health management
- circuitbreaker pattern: automatic fallback on provider failure
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from config import settings

logger = logging.getLogger(__name__)

# Progressive cooldown steps (borrowed from openakita)
COOLDOWN_STEPS = [5, 10, 20, 60]

# Circuit breaker thresholds
CIRCUIT_OPEN_THRESHOLD = 3  # failures before opening circuit
CIRCUIT_RESET_TIMEOUT = 120  # seconds before trying again


class LLMClient(ABC):
    """Base LLM client (openakita LLMProvider pattern)."""

    provider_name: str = "base"

    def __init__(self):
        self._healthy = True
        self._cooldown_until: float = 0
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False
        self._circuit_open_time: float = 0

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

    @abstractmethod
    async def stream_chat(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        """Stream chat response chunks."""
        ...

    @abstractmethod
    async def chat(self, system_prompt: str, user_message: str) -> str:
        """Non-streaming chat response."""
        ...

    @abstractmethod
    async def extract(self, system_prompt: str, user_message: str) -> str:
        """Lightweight extraction call (compiler endpoint pattern from openakita)."""
        ...


class OpenAIClient(LLMClient):
    """OpenAI-compatible LLM client."""

    provider_name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str | None = None, name: str = "openai"):
        super().__init__()
        from openai import AsyncOpenAI

        self.provider_name = name
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)
        self.model = model

    async def stream_chat(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        try:
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    self.mark_healthy()
                    yield delta.content
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat(self, system_prompt: str, user_message: str) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
            self.mark_healthy()
            return response.choices[0].message.content or ""
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def extract(self, system_prompt: str, user_message: str) -> str:
        """Lightweight extraction (openakita's think_lightweight pattern)."""
        return await self.chat(system_prompt, user_message)


class AnthropicClient(LLMClient):
    """Anthropic Claude client."""

    provider_name = "anthropic"

    def __init__(self, api_key: str, model: str):
        super().__init__()
        from anthropic import AsyncAnthropic

        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def stream_chat(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        try:
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for text in stream.text_stream:
                    self.mark_healthy()
                    yield text
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat(self, system_prompt: str, user_message: str) -> str:
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            )
            self.mark_healthy()
            return response.content[0].text
        except Exception as e:
            self.mark_unhealthy(str(e))
            raise

    async def extract(self, system_prompt: str, user_message: str) -> str:
        return await self.chat(system_prompt, user_message)


class MockLLMClient(LLMClient):
    """Fallback local client when no external API key is configured."""

    provider_name = "mock"

    async def stream_chat(self, system_prompt: str, user_message: str) -> AsyncIterator[str]:
        del system_prompt
        self.mark_healthy()
        yield (
            "No LLM API key configured. This is a local fallback response. "
            f"Your message was: {user_message}"
        )

    async def chat(self, system_prompt: str, user_message: str) -> str:
        del system_prompt
        self.mark_healthy()
        return (
            "No LLM API key configured. This is a local fallback response. "
            f"Your message was: {user_message}"
        )

    async def extract(self, system_prompt: str, user_message: str) -> str:
        del system_prompt, user_message
        self.mark_healthy()
        return "NONE"


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

    def register(self, name: str, client: LLMClient, primary: bool = False):
        """Register a provider."""
        self._providers[name] = client
        if primary:
            self._primary = name
        if name not in self._fallback_order:
            self._fallback_order.append(name)

    def get(self, name: str | None = None) -> LLMClient:
        """Get a healthy provider, with automatic fallback.

        Fallback chain: primary → fallback_order (circuit breaker pattern).
        """
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


# ──────────────────────────────────────────────────────────────
# Global singleton (nanobot pattern: create once, reuse)
# ──────────────────────────────────────────────────────────────

_registry: ProviderRegistry | None = None


def _build_registry() -> ProviderRegistry:
    """Build the provider registry from env vars."""
    registry = ProviderRegistry()

    provider = settings.llm_provider.lower()
    model = settings.llm_model

    # Register all available providers
    if settings.openai_api_key:
        client = OpenAIClient(settings.openai_api_key, model)
        registry.register("openai", client, primary=(provider == "openai"))

    if settings.anthropic_api_key:
        client = AnthropicClient(settings.anthropic_api_key, model)
        registry.register("anthropic", client, primary=(provider == "anthropic"))

    if settings.deepseek_api_key:
        client = OpenAIClient(
            settings.deepseek_api_key,
            model,
            base_url="https://api.deepseek.com/v1",
            name="deepseek",
        )
        registry.register("deepseek", client, primary=(provider == "deepseek"))

    if provider == "ollama":
        client = OpenAIClient(
            "ollama",
            model,
            base_url=f"{settings.ollama_base_url}/v1",
            name="ollama",
        )
        registry.register("ollama", client, primary=True)

    if not registry.available_providers:
        logger.warning(
            "No LLM API key configured; using mock fallback provider. "
            "Set OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY for real outputs."
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
