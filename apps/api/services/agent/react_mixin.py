"""ReAct mixin for agents that want tool-calling capability.

Usage:
    class MyAgent(ReActMixin, BaseAgent):
        react_tools = ["search_content", "lookup_progress"]
        react_max_iterations = 3

The mixin overrides stream() to run the ReAct loop when tools are defined.
If react_tools is empty or react_enabled is False, falls back to normal stream.

Borrows from:
- HelloAgents ReActAgent: opt-in per agent with tool list
- OpenAkita state machine: phase transitions during tool execution
- NanoBot: progressive tool loading (only inject tools the agent needs)
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, TaskPhase
from services.agent.tools.react_loop import react_stream, DEFAULT_MAX_ITERATIONS

logger = logging.getLogger(__name__)


class ReActMixin:
    """Mixin that adds ReAct capability to any BaseAgent subclass.

    Class attributes (override in subclass):
        react_tools: list of tool names this agent can use
        react_enabled: runtime toggle (default True)
        react_max_iterations: max tool calls per turn (default 3)
    """

    react_tools: list[str] = []
    react_enabled: bool = True
    react_max_iterations: int = DEFAULT_MAX_ITERATIONS

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Override stream to use ReAct loop when tools are available.

        Yields text chunks compatible with the orchestrator's [ACTION:] parser.
        Tool status is communicated via [TOOL_START:...] and [TOOL_DONE:...] markers
        which the orchestrator converts to tool_status SSE events.
        """
        ctx.delegated_agent = self.name  # type: ignore[attr-defined]
        ctx.transition(TaskPhase.REASONING)

        # If no tools or ReAct disabled, fall back to normal BaseAgent.stream()
        if not self.react_tools or not self.react_enabled:
            system_prompt = self.build_system_prompt(ctx)  # type: ignore[attr-defined]
            client = self.get_llm_client(ctx)  # type: ignore[attr-defined]
            ctx.transition(TaskPhase.STREAMING)
            full_response = ""
            async for chunk in client.stream_chat(system_prompt, ctx.user_message, images=ctx.images or None):
                full_response += chunk
                yield chunk
            ctx.response = full_response
            return

        # ReAct mode
        system_prompt = self.build_system_prompt(ctx)  # type: ignore[attr-defined]
        client = self.get_llm_client(ctx)  # type: ignore[attr-defined]
        ctx.transition(TaskPhase.STREAMING)

        async for event in react_stream(
            client=client,
            system_prompt=system_prompt,
            user_message=ctx.user_message,
            ctx=ctx,
            db=db,
            tool_names=self.react_tools,
            max_iterations=self.react_max_iterations,
        ):
            event_type = event["type"]

            if event_type == "thought":
                # Thoughts are internal — not streamed to user.
                # Could optionally log for debugging.
                logger.debug("ReAct thought: %.100s", event.get("content", ""))

            elif event_type == "tool_start":
                # Emit marker for orchestrator to parse as tool_status SSE event
                explanation = event.get("explanation", "")
                if explanation:
                    yield f'[TOOL_START:{event["tool"]}|{explanation}]'
                else:
                    yield f'[TOOL_START:{event["tool"]}]'

            elif event_type == "tool_result":
                explanation = event.get("explanation", "")
                if explanation:
                    yield f'[TOOL_DONE:{event["tool"]}|{explanation}]'
                else:
                    yield f'[TOOL_DONE:{event["tool"]}]'

            elif event_type == "answer":
                yield event["content"]

            elif event_type == "answer_done":
                pass  # Response already set on ctx by react_stream
