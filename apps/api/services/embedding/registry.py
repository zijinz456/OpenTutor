"""Embedding provider registry with fallback chain.

Strategy (borrowed from OpenClaw backend-config.ts):
1. Try primary provider (OpenAI if API key available)
2. On failure, automatically fall back to next available provider
3. Log fallback reason for observability

Providers are initialized lazily and cached as singletons.
"""

import logging

from services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_provider: EmbeddingProvider | None = None


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
    """Return the singleton embedding provider with fallback chain."""
    global _provider
    if _provider is not None:
        return _provider

    from config import settings

    providers: list[tuple[str, EmbeddingProvider]] = []

    # Primary: OpenAI (if API key available)
    if settings.openai_api_key:
        try:
            from services.embedding.openai_provider import OpenAIEmbedding
            providers.append(("openai", OpenAIEmbedding(settings.openai_api_key)))
            logger.info("Embedding provider registered: OpenAI text-embedding-3-small")
        except (ValueError, RuntimeError, OSError) as e:
            logger.exception("Failed to init OpenAI embedding")

    # Fallback: local sentence-transformers
    try:
        from services.embedding.local import LocalEmbedding
        providers.append(("local", LocalEmbedding()))
        logger.info("Embedding provider registered: local sentence-transformers")
    except ImportError as e:
        logger.warning("Local embedding unavailable: %s", e)
    except (OSError, RuntimeError, ValueError) as e:
        logger.warning("Local embedding init failed: %s", e)

    if not providers:
        raise RuntimeError(
            "No embedding provider available. "
            "Set OPENAI_API_KEY or install sentence-transformers."
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
