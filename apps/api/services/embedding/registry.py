"""Embedding provider registry with fallback chain.

Strategy (borrowed from OpenClaw backend-config.ts):
1. Try primary provider (OpenAI if API key available)
2. On failure, automatically fall back to next available provider
3. Log fallback reason for observability

Providers are initialized lazily and cached as singletons.

Embedding modes (EMBEDDING_MODE env var):
- "auto"  → use a fast API provider if available; skip if only slow local model
- "eager" → always compute embeddings even if slow
- "skip"  → never compute embeddings (zero-cost no-op provider)
"""

import logging

from services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_provider: EmbeddingProvider | None = None

# Provider names that are considered "fast" (API-based, not CPU-bound)
_FAST_PROVIDERS = {"openai", "deepseek"}


class NoOpEmbeddingProvider(EmbeddingProvider):
    """Returns zero vectors instantly. Used when embedding is skipped."""

    dimension = 1536

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self.dimension

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimension for _ in texts]


class FallbackEmbeddingProvider(EmbeddingProvider):
    """Wraps multiple providers with automatic fallback on failure.

    Borrowed from OpenClaw's embedding provider auto-selection pattern:
    primary provider fails → try next in chain → log fallback reason.
    """

    def __init__(self, providers: list[tuple[str, EmbeddingProvider]]):
        if not providers:
            raise RuntimeError("No embedding providers available.")
        self._providers = providers  # [(name, provider), ...]
        self._primary_name, primary = providers[0]
        self.dimension = primary.dimension

    async def embed(self, text: str) -> list[float]:
        last_error = None
        for name, provider in self._providers:
            try:
                result = await provider.embed(text)
                if name != self._primary_name:
                    logger.info(
                        "Embedding fallback: using '%s' (primary '%s' failed)",
                        name, self._primary_name,
                    )
                return result
            except (ConnectionError, TimeoutError, RuntimeError, ValueError, OSError) as e:
                last_error = e
                logger.warning("Embedding provider '%s' failed: %s", name, e)
        raise RuntimeError(
            f"All embedding providers failed. Last error: {last_error}"
        )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        last_error = None
        for name, provider in self._providers:
            try:
                result = await provider.embed_batch(texts)
                if name != self._primary_name:
                    logger.info(
                        "Embedding fallback (batch): using '%s' (primary '%s' failed)",
                        name, self._primary_name,
                    )
                return result
            except (ConnectionError, TimeoutError, RuntimeError, ValueError, OSError) as e:
                last_error = e
                logger.warning("Embedding provider '%s' batch failed: %s", name, e)
        raise RuntimeError(
            f"All embedding providers failed (batch). Last error: {last_error}"
        )


def get_embedding_provider() -> EmbeddingProvider:
    """Return the singleton embedding provider with fallback chain.

    Respects EMBEDDING_MODE:
    - "skip"  → always returns NoOpEmbeddingProvider
    - "eager" → builds full chain including slow local provider
    - "auto"  → builds chain but skips slow local-only setups (returns NoOp)
    """
    global _provider
    if _provider is not None:
        return _provider

    from config import settings

    mode = settings.embedding_mode

    # Skip mode: instant no-op
    if mode == "skip":
        _provider = NoOpEmbeddingProvider()
        logger.info("Embedding mode=skip: using no-op provider (embeddings disabled)")
        return _provider

    providers: list[tuple[str, EmbeddingProvider]] = []
    has_fast_provider = False

    # Primary: OpenAI (if API key available)
    if settings.openai_api_key:
        try:
            from services.embedding.openai_provider import OpenAIEmbedding
            providers.append(("openai", OpenAIEmbedding(settings.openai_api_key)))
            has_fast_provider = True
            logger.info("Embedding provider registered: OpenAI text-embedding-3-small")
        except (ValueError, RuntimeError, OSError) as e:
            logger.exception("Failed to init OpenAI embedding")

    # DeepSeek embedding via OpenAI-compatible API (if API key available)
    if settings.deepseek_api_key and not has_fast_provider:
        # DeepSeek does not currently offer an embedding endpoint.
        logger.debug("DeepSeek API key present but DeepSeek has no embedding endpoint")

    # LM Studio or other local OpenAI-compatible server for embeddings
    # Only attempt if user has explicitly chosen lmstudio as their LLM provider
    # (the base URL has a default value so we can't rely on it being set)
    if settings.llm_provider == "lmstudio" and not has_fast_provider:
        try:
            from services.embedding.openai_provider import OpenAIEmbedding
            provider = OpenAIEmbedding(
                api_key="lm-studio",  # pragma: allowlist secret
                model="text-embedding-nomic-embed-text-v1.5",
            )
            # Override client to point at LM Studio
            from openai import AsyncOpenAI
            provider.client = AsyncOpenAI(
                api_key="lm-studio",  # pragma: allowlist secret
                base_url=settings.lmstudio_base_url,
            )
            providers.append(("lmstudio", provider))
            # LM Studio embedding is GPU-accelerated and async, treat as fast
            has_fast_provider = True
            logger.info("Embedding provider registered: LM Studio at %s", settings.lmstudio_base_url)
        except (ValueError, RuntimeError, OSError, ImportError) as e:
            logger.debug("LM Studio embedding unavailable: %s", e)

    # Auto mode early exit: if no fast provider found, skip local model loading entirely
    if mode == "auto" and not has_fast_provider:
        _provider = NoOpEmbeddingProvider()
        logger.info(
            "Embedding mode=auto: no fast provider available. "
            "Skipping embeddings to avoid blocking ingestion. "
            "Set EMBEDDING_MODE=eager to force local embeddings, or "
            "provide OPENAI_API_KEY for fast API-based embeddings."
        )
        return _provider

    # Fallback: local sentence-transformers (only loaded in eager mode or when fast provider exists)
    try:
        from services.embedding.local import LocalEmbedding
        providers.append(("local", LocalEmbedding()))
        logger.info("Embedding provider registered: local sentence-transformers")
    except ImportError as e:
        logger.warning("Local embedding unavailable: %s", e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Local embedding init failed: %s", e)

    if not providers:
        if mode == "auto":
            _provider = NoOpEmbeddingProvider()
            logger.info(
                "Embedding mode=auto: no providers available. "
                "Using no-op provider. Search will use keyword-only fallback."
            )
            return _provider
        raise RuntimeError(
            "No embedding provider available. "
            "Set OPENAI_API_KEY or install sentence-transformers, "
            "or set EMBEDDING_MODE=skip to disable embeddings."
        )

    # Single provider → use directly; multiple → wrap with fallback
    if len(providers) == 1:
        _provider = providers[0][1]
    else:
        _provider = FallbackEmbeddingProvider(providers)
        logger.info(
            "Embedding fallback chain: %s",
            " → ".join(name for name, _ in providers),
        )

    return _provider


def is_noop_provider() -> bool:
    """Check whether the current provider is a no-op (embeddings disabled)."""
    try:
        provider = get_embedding_provider()
        return isinstance(provider, NoOpEmbeddingProvider)
    except RuntimeError:
        return True


def reset_provider() -> None:
    """Reset the cached provider (for testing)."""
    global _provider
    _provider = None
