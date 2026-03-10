"""Abstract base class for LLM clients.

Combines the CircuitBreakerMixin with the abstract LLM interface.
All provider clients inherit from LLMClient.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from services.llm.circuit_breaker import CircuitBreakerMixin


class LLMClient(CircuitBreakerMixin, ABC):
    """Base LLM client (openakita LLMProvider pattern).

    Token tracking (OpenClaw SessionEntry pattern):
    - chat() and extract() return tuple[str, dict] with usage info
    - stream_chat() stores usage in _last_usage, accessible via get_last_usage()
    """

    provider_name: str = "base"

    def __init__(self):
        super().__init__()
        self._last_usage: dict = {}

    def get_last_usage(self) -> dict:
        """Get token usage from the last API call (useful after streaming)."""
        return self._last_usage

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
