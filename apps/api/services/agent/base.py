"""Base agent class for the multi-agent architecture.

Borrows from:
- MetaGPT Role: profile / goal / constraints pattern
- HelloAgents ReActAgent: Thought -> Action -> Observation loop
- OpenClaw agent-scope: independent workspace, model config, memory config
"""

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base_mixins import BackgroundTaskMixin, DelegationMixin
from services.agent.prompt_builder import PromptBuildingMixin
from services.agent.state import AgentContext, InputRequirement, TaskPhase

logger = logging.getLogger(__name__)


class BaseAgent(DelegationMixin, BackgroundTaskMixin, PromptBuildingMixin, ABC):
    """Base class for all specialist agents.

    Each agent has:
    - name: unique identifier
    - profile: role description (MetaGPT pattern)
    - system_prompt_template: customizable per-agent prompt
    - model_preference: different agents can use different model sizes
    """

    name: str = "base"
    profile: str = "A generic learning assistant agent."
    model_preference: str | None = None  # None = use default, "small" / "large"

    def get_required_inputs(self) -> list[InputRequirement]:
        """Return input requirements for pre-task questioning. Override in subclasses."""
        return []

    def get_llm_client(self, ctx: AgentContext | None = None):
        """Get LLM client with 3-tier complexity routing when context is available.

        When ctx is provided, uses complexity scoring to select fast/standard/frontier.
        Falls back to legacy model_preference ("large"/"small") when ctx is None.
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

    @abstractmethod
    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Agent-specific execution logic. Subclasses must implement."""
        ...

    async def delegate(
        self,
        target_agent_name: str,
        sub_message: str,
        ctx: AgentContext,
        db: AsyncSession,
    ) -> str:
        """Delegate a sub-task to another specialist agent.

        Returns the sub-agent's response text. The delegation is tracked
        in ctx.metadata for observability.
        """
        from services.agent.registry import AGENT_REGISTRY

        target = AGENT_REGISTRY.get(target_agent_name)
        if not target:
            logger.warning("Delegation target '%s' not found", target_agent_name)
            return f"[delegation failed: unknown agent '{target_agent_name}']"

        # Capability escalation check
        from services.agent.capabilities import check_delegation_escalation

        allowed, reason = check_delegation_escalation(self.name, target_agent_name)
        if not allowed:
            logger.warning("Delegation blocked: %s -> %s: %s", self.name, target_agent_name, reason)
            return f"[delegation blocked: {reason}]"

        # Create a sub-context preserving identity but with new message
        sub_ctx = AgentContext(
            user_id=ctx.user_id,
            course_id=ctx.course_id,
            user_message=sub_message,
            preferences=ctx.preferences,
            content_docs=ctx.content_docs,
            memories=ctx.memories,
            scene=ctx.scene,
        )

        logger.info("Agent '%s' delegating to '%s'", self.name, target_agent_name)
        sub_ctx = await target.run(sub_ctx, db)

        # Track delegation chain
        delegations = ctx.metadata.setdefault("delegations", [])
        delegations.append({
            "from": self.name,
            "to": target_agent_name,
            "message": sub_message[:200],
            "response_length": len(sub_ctx.response),
        })

        return sub_ctx.response

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream response chunks for SSE. Default: run then yield full response."""
        ctx = await self.run(ctx, db)
        if ctx.response:
            yield ctx.response
