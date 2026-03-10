"""LLM Provider Registry with circuit breaker pattern + token tracking.

This is the main entry point. All public names are re-exported here for
backward compatibility -- existing imports like
``from services.llm.router import get_llm_client`` continue to work.

Internal implementation lives in:
- circuit_breaker.py  -- progressive cooldown + circuit breaker
- base_client.py      -- abstract LLMClient ABC
- providers/          -- OpenAIClient, AnthropicClient, MockLLMClient
"""

from __future__ import annotations

import asyncio
import threading
import time
import logging

from config import settings

# ── Re-exports (backward compatibility) ──────────────────────
from services.llm.circuit_breaker import (  # noqa: F401
    COOLDOWN_STEPS,
    CIRCUIT_OPEN_THRESHOLD,
    CIRCUIT_RESET_TIMEOUT,
)
from services.llm.base_client import LLMClient  # noqa: F401
from services.llm.providers.openai_client import (  # noqa: F401
    OpenAIClient,
    _build_openai_user_content,
)
from services.llm.providers.anthropic_client import (  # noqa: F401
    AnthropicClient,
    _build_anthropic_user_content,
)
from services.llm.providers.mock_client import MockLLMClient  # noqa: F401

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    """Raised when AI features are used without a configured real provider."""


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
        self._probe_task: "asyncio.Task[None] | None" = None

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

        Fallback chain: model_variants -> primary -> fallback_order.
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
        except Exception as e:  # Catch-all: wraps arbitrary probe failures into health status dict
            logger.debug("Provider %s probe failed: %s", name, e)
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
# Registry builder and global singleton
# ──────────────────────────────────────────────────────────────

_registry: ProviderRegistry | None = None
_registry_lock = threading.Lock()


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
        except (ConnectionError, ValueError, RuntimeError, OSError) as e:
            logger.exception("LiteLLM registration failed")

    # --- Model size variants (agent preference routing) ---
    for attr, hint in [("llm_model_large", "large"), ("llm_model_small", "small"),
                       ("llm_model_fast", "fast"), ("llm_model_standard", "standard"),
                       ("llm_model_frontier", "frontier")]:
        variant_model = getattr(settings, attr, None)
        if variant_model and variant_model != model:
            _register_variant(registry, provider, variant_model, hint)
    # Alias fallbacks: fast<->small, frontier<->large
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
    tries the next available provider.  Thread-safe initialization.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = _build_registry()
    return _registry.get(provider)


def get_registry() -> ProviderRegistry:
    """Get the global provider registry (thread-safe)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = _build_registry()
    return _registry
