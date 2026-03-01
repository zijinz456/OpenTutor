"""Base agent class for the multi-agent architecture.

Borrows from:
- MetaGPT Role: profile / goal / constraints pattern
- HelloAgents ReActAgent: Thought → Action → Observation loop
- OpenClaw agent-scope: independent workspace, model config, memory config
"""

import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
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

    def get_llm_client(self):
        """Get LLM client respecting model_preference.

        Maps model_preference to provider selection:
        - "large": use primary provider (best model)
        - "small": try lightweight/cheaper provider first
        - None: use default
        """
        from services.llm.router import get_llm_client
        # model_preference is a hint; the registry decides the actual provider
        return get_llm_client(self.model_preference)

    async def run(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Execute the agent's task. Template method pattern."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)
        try:
            ctx = await self.execute(ctx, db)
            return ctx
        except Exception as e:
            logger.error("Agent %s failed: %s", self.name, e, exc_info=True)
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
        from services.agent.orchestrator import AGENT_REGISTRY

        target = AGENT_REGISTRY.get(target_agent_name)
        if not target:
            logger.warning("Delegation target '%s' not found", target_agent_name)
            return f"[delegation failed: unknown agent '{target_agent_name}']"

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

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Build agent-specific system prompt with context + scene behavior injection."""
        from services.agent.scene_behavior import get_scene_with_tab_context

        parts = [self.profile]

        # v3: Scene-aware behavior rules
        scene_section = get_scene_with_tab_context(ctx.scene, ctx.active_tab, ctx.tab_context)
        parts.append(scene_section)

        # Preference injection
        if ctx.preferences:
            pref_lines = [f"- {k}: {v}" for k, v in ctx.preferences.items()]
            parts.append(f"\nUser preferences:\n" + "\n".join(pref_lines))

        # Memory context
        if ctx.memories:
            parts.append("\n## Previous Interactions (memory):\n")
            for mem in ctx.memories:
                parts.append(f"- {mem.get('summary', '')}")

        # RAG context
        if ctx.content_docs:
            parts.append("\n## Course Materials (already retrieved for this query):\n")
            parts.append("Note: These sections were auto-retrieved. Only use search_content tool if you need DIFFERENT content.\n")
            for doc in ctx.content_docs:
                parts.append(f"### {doc.get('title', '')}\n{doc.get('content', '')[:1500]}\n")

        return "\n".join(parts)
