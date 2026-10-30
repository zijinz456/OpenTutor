"""Abstract base class for LLM clients.

Combines the CircuitBreakerMixin with the abstract LLM interface.
All provider clients inherit from LLMClient.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator

from services.llm.circuit_breaker import CircuitBreakerMixin


def normalize_history(history: list[dict] | None, current_message: str | None = None) -> list[dict]:
    """Turn raw conversation history into a clean alternating user/assistant list.

    - keeps only user/assistant roles with non-empty string content
    - merges consecutive same-role messages (providers like Anthropic require alternation)
    - drops a trailing user message (the frontend includes the message being sent
      as the last history item; the caller passes it separately)
    """
    cleaned: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        if cleaned and cleaned[-1]["role"] == role:
            cleaned[-1]["content"] += "\n\n" + content
        else:
            cleaned.append({"role": role, "content": content})

    while cleaned and cleaned[-1]["role"] == "user":
        last = cleaned.pop()
        if current_message is not None and last["content"] != current_message.strip():
            # A dangling user turn that is not the current message: keep it as context
            cleaned.append(last)
            break
    # Must start with a user turn for strict providers
    while cleaned and cleaned[0]["role"] != "user":
        cleaned.pop(0)
    return cleaned


def build_chat_messages(
    system_prompt: str,
    user_content,
    history: list[dict] | None = None,
) -> list[dict]:
    """Standard OpenAI-style message list: system, prior turns, current user turn."""
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_content})
    return messages


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
    async def stream_chat(
        self,
        system_prompt: str,
        user_message: str,
        images: list[dict] | None = None,
        history: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        """Stream chat response chunks. Token usage stored in _last_usage.

        images: optional list of {"data": base64_str, "media_type": "image/png"|...}
        history: prior turns as [{"role": "user"|"assistant", "content": str}], already normalized
        """
        ...

    @abstractmethod
    async def chat(
        self,
        system_prompt: str,
        user_message: str,
        images: list[dict] | None = None,
        history: list[dict] | None = None,
    ) -> tuple[str, dict]:
        """Non-streaming chat response. Returns (content, usage_dict).

        images: optional list of {"data": base64_str, "media_type": "image/png"|...}
        history: prior turns as [{"role": "user"|"assistant", "content": str}], already normalized
        """
        ...

    @abstractmethod
    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        """Lightweight extraction call. Returns (content, usage_dict)."""
        ...
