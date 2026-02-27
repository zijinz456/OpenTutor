"""TeachingAgent — handles LEARN intent with RAG + personalized explanation.

Borrows from:
- HelloAgents TutorAgent: structured teaching with context
- MetaGPT Role: profile/goal/constraints
- OpenClaw agent-scope: independent prompt + model config
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase
from services.agent.tool_loader import get_tools_for_scene

logger = logging.getLogger(__name__)


class TeachingAgent(BaseAgent):
    """Handles knowledge questions, explanations, and concept learning."""

    name = "teaching"
    profile = (
        "You are OpenTutor, a personalized learning assistant.\n"
        "Answer based on the course materials provided below.\n"
        "If the answer is not in the materials, say so clearly.\n"
        "Adapt your explanation style to the student's preferences.\n"
        "Cite specific sections when possible."
    )
    model_preference = "large"  # Teaching needs the best model

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
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream teaching response for SSE."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client()

        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message):
            full_response += chunk
            yield chunk

        ctx.response = full_response
