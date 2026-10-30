"""Base agent class for the multi-agent architecture.

Borrows from:
- MetaGPT Role: profile / goal / constraints pattern
- HelloAgents ReActAgent: Thought -> Action -> Observation loop
- OpenClaw agent-scope: independent workspace, model config, memory config
"""

import logging
from abc import ABC
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.prompt_builder import PromptBuildingMixin
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class BaseAgent(PromptBuildingMixin, ABC):
    """Base class for all specialist agents.

    Each agent has:
    - name: unique identifier
    - profile: role description (MetaGPT pattern)
    - system_prompt_template: customizable per-agent prompt
    - model_preference: different agents can use different model sizes
    """

    name: str = "base"
    profile: str = "A generic learning assistant agent."
    model_preference: str | None = None  # None = use default, else "fast" / "standard" / "frontier"

    def get_llm_client(self, ctx: AgentContext | None = None):
        """Get LLM client with 3-tier complexity routing when context is available.

        When ctx is provided, uses complexity scoring to select fast/standard/frontier.
        Falls back to the agent's static model_preference tier when ctx is None.
        """
        from services.llm.router import get_llm_client

        if ctx is not None:
            try:
                from services.llm.complexity import resolve_tier

                tier = resolve_tier(
                    agent_name=self.name,
                    message=ctx.user_message,
                    intent=ctx.intent.value if ctx.intent else "general",
                    scene=ctx.scene or "study_session",
                    history_length=len(ctx.conversation_history),
                    has_rag_context=bool(ctx.content_docs),
                )
                return get_llm_client(tier.value)
            except ImportError:
                logger.debug("llm.complexity module not available, using model_preference fallback")

        # Legacy fallback
        return get_llm_client(self.model_preference)

    async def run(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Execute the agent's task. Template method pattern."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        try:
            ctx = await self.execute(ctx, db)
            return ctx
        except Exception as e:
            logger.exception("Agent %s failed: %s", self.name, e)
            ctx.mark_failed(str(e))
            return ctx

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Non-streaming execution.

        Streaming agents (the chat path) only implement ``stream``; this
        default drains that stream so ``run`` still works for them.  Agents
        that are only ever called synchronously override ``execute``.
        """
        if type(self).stream is BaseAgent.stream:
            raise NotImplementedError(f"{self.name} must implement execute() or stream()")
        chunks: list[str] = []
        async for chunk in self.stream(ctx, db):
            chunks.append(chunk)
        if not ctx.response:
            ctx.response = "".join(chunks)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream response chunks for SSE. Default: run then yield full response."""
        ctx = await self.run(ctx, db)
        if ctx.response:
            yield ctx.response
