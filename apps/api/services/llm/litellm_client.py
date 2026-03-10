"""LiteLLM provider integration.

Opt-in alternative that provides access to 100+ LLM backends through
the litellm library. Enable via USE_LITELLM=true in environment.

When enabled, LiteLLM acts as a universal adapter -- you can use any
model string that litellm supports (e.g., "anthropic/claude-3-opus",
"openai/gpt-4o", "azure/gpt-4", "bedrock/claude-3", etc.)
"""

import json
import logging
from typing import Any, AsyncIterator

import httpx
import openai

from services.llm.base_client import LLMClient

logger = logging.getLogger(__name__)


class LiteLLMClient(LLMClient):
    """LLM client backed by the litellm library.

    Provides a unified interface to 100+ LLM providers through litellm's
    routing layer. Supports streaming, function calling, and token tracking.
    """

    provider_name = "litellm"

    def __init__(self, model: str, api_base: str | None = None, api_key: str | None = None):
        super().__init__()
        self.model = model
        self.api_base = api_base
        self.api_key = api_key

        # Verify litellm is available
        try:
            import litellm
            self._litellm = litellm
            # Suppress litellm's verbose logging
            litellm.suppress_debug_info = True
        except ImportError:
            raise ImportError(
                "litellm is required for USE_LITELLM=true. "
                "Install it with: pip install litellm"
            )

    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": True,
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base
            if self.api_key:
                kwargs["api_key"] = self.api_key

            response = await self._litellm.acompletion(**kwargs)

            marked_healthy = False
            async for chunk in response:
                if hasattr(chunk, "usage") and chunk.usage:
                    self._last_usage = {
                        "input_tokens": getattr(chunk.usage, "prompt_tokens", 0) or 0,
                        "output_tokens": getattr(chunk.usage, "completion_tokens", 0) or 0,
                    }
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    if not marked_healthy:
                        self.mark_healthy()
                        marked_healthy = True
                    yield delta.content
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise
        except Exception as e:  # Catch-all: litellm may raise provider-specific errors
            self.mark_unhealthy(str(e))
            raise

    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]

            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base
            if self.api_key:
                kwargs["api_key"] = self.api_key

            response = await self._litellm.acompletion(**kwargs)

            self.mark_healthy()
            usage = {
                "input_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
            }
            self._last_usage = usage
            return response.choices[0].message.content or "", usage
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise
        except Exception as e:  # Catch-all: litellm may raise provider-specific errors
            self.mark_unhealthy(str(e))
            raise

    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        return await self.chat(system_prompt, user_message)

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> tuple[str, list[dict], dict]:
        """Chat with function calling via litellm."""
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base
            if self.api_key:
                kwargs["api_key"] = self.api_key

            response = await self._litellm.acompletion(**kwargs)

            self.mark_healthy()
            msg = response.choices[0].message
            text = msg.content or ""
            tool_calls: list[dict[str, Any]] = []

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {"raw": tc.function.arguments}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })

            usage = {
                "input_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "output_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
            }
            self._last_usage = usage
            return text, tool_calls, usage
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise
        except Exception as e:  # Catch-all: litellm may raise provider-specific errors
            self.mark_unhealthy(str(e))
            raise
