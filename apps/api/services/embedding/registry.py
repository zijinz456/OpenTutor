"""Embedding provider registry (singleton factory).

Strategy: use OpenAI if API key available, otherwise try local
sentence-transformers. Follows the same pattern as services/llm/router.py.
"""

import logging

from services.embedding.base import EmbeddingProvider

logger = logging.getLogger(__name__)

_provider: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    """Return the singleton embedding provider."""
    global _provider
    if _provider is not None:
        return _provider

    from config import settings

    if settings.openai_api_key:
        from services.embedding.openai_provider import OpenAIEmbedding
        _provider = OpenAIEmbedding(settings.openai_api_key)
        logger.info("Embedding provider: OpenAI text-embedding-3-small")
        return _provider

    try:
        from services.embedding.local import LocalEmbedding
        _provider = LocalEmbedding()
        logger.info("Embedding provider: local sentence-transformers")
        return _provider
    except ImportError:
        pass

    raise RuntimeError(
        "No embedding provider available. "
        "Set OPENAI_API_KEY or install sentence-transformers."
    )
