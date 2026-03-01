"""TeachingAgent — handles LEARN intent with RAG + personalized explanation.

Borrows from:
- HelloAgents TutorAgent: structured teaching with context
- MetaGPT Role: profile/goal/constraints
- OpenClaw agent-scope: independent prompt + model config
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext
from services.agent.tool_loader import get_tools_for_scene

logger = logging.getLogger(__name__)


class TeachingAgent(ReActMixin, BaseAgent):
    """Handles knowledge questions, explanations, and concept learning."""

    name = "teaching"
    profile = (
        "You are OpenTutor Zenus, a personalized learning assistant.\n"
        "Answer based on the course materials provided below.\n"
        "If the answer is not in the materials, say so clearly.\n"
        "Adapt your explanation style to the student's preferences.\n"
        "Cite specific sections when possible."
    )
    model_preference = "large"  # Teaching needs the best model
    react_tools = ["search_content", "lookup_progress", "get_course_outline"]

    def build_system_prompt(self, ctx: AgentContext) -> str:
        """Teaching-specific prompt with scene-aware behavior + tools + RAG context."""
        # Base class handles: profile, scene behavior, preferences, memories, RAG
        base = super().build_system_prompt(ctx)
        # Add scene-based tool injection (saves ~30% tokens)
        scene_tools = get_tools_for_scene(ctx.scene, include_preference=False)
        return f"{base}\n{scene_tools}"

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate teaching response using RAG context."""
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client()
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message, images=ctx.images or None)
        return ctx
