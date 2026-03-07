"""Local embedding provider using sentence-transformers (384 dimensions).

Optional dependency: install via `pip install sentence-transformers`.
This provider zero-pads to 1536 dimensions to stay compatible with
the fixed-length embedding schema used by local SQLite mode.
"""

import asyncio
from functools import partial

from services.embedding.base import EmbeddingProvider

TARGET_DIM = 1536


class LocalEmbedding(EmbeddingProvider):
    dimension = TARGET_DIM  # Zero-padded to match the embedding column size

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(model_name)
        self._native_dim = self._model.get_sentence_embedding_dimension()

    def _pad(self, vec: list[float]) -> list[float]:
        if len(vec) >= TARGET_DIM:
            return vec[:TARGET_DIM]
        return vec + [0.0] * (TARGET_DIM - len(vec))

    async def embed(self, text: str) -> list[float]:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, partial(self._model.encode, text)
        )
        return self._pad(result.tolist())

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            None, partial(self._model.encode, texts)
        )
        return [self._pad(r.tolist()) for r in results]
