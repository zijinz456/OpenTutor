"""OpenAI embedding provider (text-embedding-3-small, 1536 dimensions)."""

from services.embedding.base import EmbeddingProvider


class OpenAIEmbedding(EmbeddingProvider):
    dimension = 1536

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def embed(self, text: str) -> list[float]:
        response = await self.client.embeddings.create(
            model=self.model,
            input=text[:8000],
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # OpenAI supports up to 2048 inputs per batch
        response = await self.client.embeddings.create(
            model=self.model,
            input=[t[:8000] for t in texts],
        )
        return [d.embedding for d in sorted(response.data, key=lambda x: x.index)]
