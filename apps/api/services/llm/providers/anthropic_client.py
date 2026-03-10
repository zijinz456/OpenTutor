"""Anthropic Claude LLM client with vision support and tool calling."""

import json
import logging
from typing import Any, AsyncIterator

import httpx
import anthropic

from services.llm.base_client import LLMClient

logger = logging.getLogger(__name__)


def _build_anthropic_user_content(text: str, images: list[dict] | None = None) -> str | list[dict]:
    """Build Anthropic user content with optional vision image blocks."""
    if not images:
        return text
    content: list[dict] = []
    for img in images:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": img.get("media_type", "image/png"), "data": img["data"]},
        })
    content.append({"type": "text", "text": text})
    return content


class AnthropicClient(LLMClient):
    """Anthropic Claude client."""

    provider_name = "anthropic"

    def __init__(self, api_key: str, model: str):
        super().__init__()
        from anthropic import AsyncAnthropic

        # Timeout: 10s connect, 120s read (streaming), 30s write, 10s pool
        self.client = AsyncAnthropic(
            api_key=api_key,
            timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10),
        )
        self.model = model

    async def stream_chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> AsyncIterator[str]:
        try:
            user_content = _build_anthropic_user_content(user_message, images)
            async with self.client.messages.stream(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            ) as stream:
                marked_healthy = False
                async for text in stream.text_stream:
                    if not marked_healthy:
                        self.mark_healthy()
                        marked_healthy = True
                    yield text
                # Capture usage after stream completes
                final = await stream.get_final_message()
                self._last_usage = {
                    "input_tokens": final.usage.input_tokens if final.usage else 0,
                    "output_tokens": final.usage.output_tokens if final.usage else 0,
                }
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise

    async def chat(self, system_prompt: str, user_message: str, images: list[dict] | None = None) -> tuple[str, dict]:
        try:
            user_content = _build_anthropic_user_content(user_message, images)
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            self.mark_healthy()
            usage = {
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return response.content[0].text, usage
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIError) as e:
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
        """Chat with Anthropic tool_use support.

        Converts OpenAI-format tool schemas to Anthropic format, calls the API,
        and normalizes the response back to the common format.
        """
        # Convert OpenAI tool schema -> Anthropic format
        anthropic_tools = []
        for t in tools:
            func = t.get("function", t)
            anthropic_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })

        # Extract system prompt from messages (Anthropic uses separate system param)
        system_prompt = ""
        api_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_prompt = msg.get("content", "")
            elif msg["role"] == "tool":
                # Anthropic expects tool_result blocks
                api_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                # Convert assistant tool_calls to Anthropic format
                content_blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    func = tc.get("function", tc)
                    try:
                        args = json.loads(func["arguments"]) if isinstance(func["arguments"], str) else func["arguments"]
                    except (json.JSONDecodeError, TypeError):
                        logger.warning("Malformed tool call arguments for %s, using empty dict", func.get("name", "?"))
                        args = {}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": func["name"],
                        "input": args,
                    })
                api_messages.append({"role": "assistant", "content": content_blocks})
            else:
                api_messages.append(msg)

        # Anthropic requires alternating user/assistant roles.
        # Merge consecutive same-role messages (e.g., multiple tool_results -> one user msg)
        merged_messages: list[dict] = []
        for msg in api_messages:
            if merged_messages and merged_messages[-1]["role"] == msg["role"]:
                prev = merged_messages[-1]
                # Merge content: ensure both are lists, then concatenate
                prev_content = prev["content"] if isinstance(prev["content"], list) else [{"type": "text", "text": prev["content"]}]
                new_content = msg["content"] if isinstance(msg["content"], list) else [{"type": "text", "text": msg["content"]}]
                prev["content"] = prev_content + new_content
            else:
                merged_messages.append({**msg})

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=system_prompt,
                messages=merged_messages,
                tools=anthropic_tools,
            )
            self.mark_healthy()

            text = ""
            tool_calls: list[dict[str, Any]] = []
            for block in response.content:
                if block.type == "text":
                    text += block.text
                elif block.type == "tool_use":
                    tool_calls.append({
                        "id": block.id,
                        "name": block.name,
                        "arguments": block.input,
                    })

            usage = {
                "input_tokens": response.usage.input_tokens if response.usage else 0,
                "output_tokens": response.usage.output_tokens if response.usage else 0,
            }
            self._last_usage = usage
            return text, tool_calls, usage
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIError) as e:
            self.mark_unhealthy(str(e))
            raise
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            self.mark_unhealthy(str(e))
            raise

    async def extract(self, system_prompt: str, user_message: str) -> tuple[str, dict]:
        return await self.chat(system_prompt, user_message)
