"""OpenAI-compatible LLM client with vision support and tool calling."""

import json
import logging
from typing import Any, AsyncIterator

import httpx
import openai

from services.llm.base_client import LLMClient

logger = logging.getLogger(__name__)


def _build_openai_user_content(text: str, images: list[dict] | None = None) -> str | list[dict]:
    """Build OpenAI user content with optional vision image blocks."""
    if not images:
        return text
    content: list[dict] = [{"type": "text", "text": text}]
    for img in images:
        data_uri = f"data:{img.get('media_type', 'image/png')};base64,{img['data']}"
        content.append({"type": "image_url", "image_url": {"url": data_uri, "detail": "auto"}})
    return content


class OpenAIClient(LLMClient):
    """OpenAI-compatible LLM client."""

    provider_name = "openai"

    # Local backends that may not support stream_options
    _NO_STREAM_OPTIONS = {"ollama", "vllm", "lmstudio", "textgenwebui", "custom"}

    def __init__(self, api_key: str, model: str, base_url: str | None = None, name: str = "openai"):
        super().__init__()
        from openai import AsyncOpenAI

        self.provider_name = name
        self._supports_stream_options = name not in self._NO_STREAM_OPTIONS
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        # Timeout: 10s connect, 120s read (streaming), 30s write, 10s pool
        kwargs["timeout"] = httpx.Timeout(connect=10, read=120, write=30, pool=10)
        self.client = AsyncOpenAI(**kwargs)
        self.model = model

    async def ping(self) -> bool:
        """Active liveness probe for local backends (OpenClaw pattern).

        Classifies errors: unreachable / auth / rate_limit / timeout / server_error.
        """
        if self.provider_name not in self._NO_STREAM_OPTIONS:
            return self.is_healthy  # Cloud APIs: trust cached status
        try:
            base = str(self.client.base_url).rstrip("/")
            async with httpx.AsyncClient(timeout=5.0) as http:
                resp = await http.get(f"{base}/models")
            if resp.status_code < 400:
                self.mark_healthy()
                return True
            if resp.status_code in (401, 403):
                self.mark_unhealthy(f"auth_error ({resp.status_code})")
            elif resp.status_code == 429:
                self.mark_unhealthy("rate_limited")
            elif resp.status_code >= 500:
                self.mark_unhealthy(f"server_error ({resp.status_code})")
            else:
                self.mark_unhealthy(f"unexpected_status ({resp.status_code})")
            return False
        except httpx.ConnectError as e:
            self.mark_unhealthy("unreachable")
            return False
        except httpx.TimeoutException as e:
            self.mark_unhealthy("timeout")
            return False
        except httpx.HTTPStatusError as e:
            self.mark_unhealthy(f"probe_error: {e}")
            return False
        except Exception as e:  # Catch-all: unexpected probe failures
            self.mark_unhealthy(f"probe_error: {e}")
            return False

    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        try:
            user_content = _build_openai_user_content(user_message, images)
            create_kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                "stream": True,
            }
            if self._supports_stream_options:
                create_kwargs["stream_options"] = {"include_usage": True}
            stream = await self.client.chat.completions.create(**create_kwargs)
            marked_healthy = False
            async for chunk in stream:
                if chunk.usage:
                    self._last_usage = {
                        "input_tokens": chunk.usage.prompt_tokens or 0,
                        "output_tokens": chunk.usage.completion_tokens or 0,
                    }
                if chunk.choices and chunk.choices[0].delta.content:
                    if not marked_healthy:
                        self.mark_healthy()
                        marked_healthy = True
                    yield chunk.choices[0].delta.content
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        try:
            user_content = _build_openai_user_content(user_message, images)
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
            )
            self.mark_healthy()
            usage = {
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return response.choices[0].message.content or "", usage
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> tuple[str, list[dict], dict]:
        """Chat with OpenAI native function calling.

        Args:
            messages: Full conversation history (system, user, assistant, tool).
            tools: OpenAI function calling schemas.

        Returns:
            (text_response, tool_calls, usage_dict)
            tool_calls: [{"id": str, "name": str, "arguments": dict}, ...]
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
            )
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
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return text, tool_calls, usage
        except (openai.APIConnectionError, openai.APITimeoutError, openai.RateLimitError, openai.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise

    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        """Lightweight extraction (openakita's think_lightweight pattern)."""
        return await self.chat(system_prompt, user_message)
