"""Mock LLM client for fallback when no API key is configured."""

from typing import AsyncIterator

from services.llm.base_client import LLMClient


class MockLLMClient(LLMClient):
    """Fallback local client when no external API key is configured."""

    provider_name = "mock"

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate for mock tracking."""
        return max(1, len(text) // 4)

    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        self.mark_healthy()
        img_note = f" (with {len(images)} image(s))" if images else ""
        content = (
            "No LLM API key configured. This is a local fallback response. "
            f"Your message was: {user_message}{img_note}"
        )
        self._last_usage = {
            "input_tokens": self._estimate_tokens(system_prompt + user_message),
            "output_tokens": self._estimate_tokens(content),
        }
        yield content

    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        self.mark_healthy()
        img_note = f" (with {len(images)} image(s))" if images else ""
        content = (
            "No LLM API key configured. This is a local fallback response. "
            f"Your message was: {user_message}{img_note}"
        )
        usage = {
            "input_tokens": self._estimate_tokens(system_prompt + user_message),
            "output_tokens": self._estimate_tokens(content),
        }
        self._last_usage = usage
        return content, usage

    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        self.mark_healthy()
        usage = {
            "input_tokens": self._estimate_tokens(system_prompt + user_message),
            "output_tokens": 1,
        }
        self._last_usage = usage
        return "NONE", usage
