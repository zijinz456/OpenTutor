"""LLM provider router with env-var switching.

Borrows from:
- openakita Brain pattern: thin wrapper, dual endpoints (main + compiler)
- nanobot Provider Registry: keyword-based provider matching
- openakita LLMProvider base: progressive cooldown, health management

Phase 0: Simple env-var switching. Phase 1: Full Provider Registry + LiteLLM.
"""

import time
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from config import settings

logger = logging.getLogger(__name__)

# Progressive cooldown steps (borrowed from openakita)
COOLDOWN_STEPS = [5, 10, 20, 60]


class LLMClient(ABC):
    """Base LLM client (openakita LLMProvider pattern)."""

    def __init__(self):
        self._healthy = True
        self._cooldown_until: float = 0
        self._consecutive_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        if self._cooldown_until > 0 and time.time() >= self._cooldown_until:
            self._healthy = True
            self._cooldown_until = 0
        return self._healthy

    def mark_unhealthy(self, error: str):
        """Progressive cooldown (borrowed from openakita)."""
        self._healthy = False
        self._consecutive_failures += 1
        idx = min(self._consecutive_failures - 1, len(COOLDOWN_STEPS) - 1)
        cooldown = COOLDOWN_STEPS[idx]
        self._cooldown_until = time.time() + cooldown
        logger.warning(f"LLM unhealthy: {error}, cooldown {cooldown}s")

    def mark_healthy(self):
        self._healthy = True
        self._consecutive_failures = 0
        self._cooldown_until = 0

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

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        super().__init__()
        from openai import AsyncOpenAI

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
        """Lightweight extraction (openakita's think_lightweight pattern).
        Uses smaller model for cost efficiency."""
        return await self.chat(system_prompt, user_message)


class AnthropicClient(LLMClient):
    """Anthropic Claude client."""

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


# Singleton client (nanobot pattern: create once, reuse)
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get or create LLM client based on env vars.

    Provider matching borrowed from nanobot's keyword-based registry:
    - LLM_PROVIDER env var → direct match
    - Falls back to first available API key
    """
    global _client
    if _client and _client.is_healthy:
        return _client

    provider = settings.llm_provider.lower()
    model = settings.llm_model

    if provider == "anthropic" and settings.anthropic_api_key:
        _client = AnthropicClient(settings.anthropic_api_key, model)
    elif provider == "deepseek" and settings.deepseek_api_key:
        _client = OpenAIClient(
            settings.deepseek_api_key,
            model,
            base_url="https://api.deepseek.com/v1",
        )
    elif provider == "ollama":
        _client = OpenAIClient(
            "ollama",
            model,
            base_url=f"{settings.ollama_base_url}/v1",
        )
    elif settings.openai_api_key:
        _client = OpenAIClient(settings.openai_api_key, model)
    else:
        raise RuntimeError(
            "No LLM API key configured. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, "
            "or DEEPSEEK_API_KEY in your .env file."
        )

    return _client
