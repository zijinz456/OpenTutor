"""ExerciseAgent — handles QUIZ intent for generating practice problems.

Borrows from:
- HelloAgents ExerciseAgent: structured quiz generation
- Spec Section 5: generate_quiz tool with Bloom's taxonomy levels
- quizperai: answer + explanation generation pattern
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class ExerciseAgent(BaseAgent):
    """Generates quizzes, exercises, and practice problems."""

    name = "exercise"
    profile = (
        "You are OpenTutor's Exercise Generator.\n"
        "Create practice problems tailored to the student's level and the course materials.\n"
        "Follow Bloom's taxonomy for difficulty levels:\n"
        "- remember: recall facts\n"
        "- understand: explain concepts\n"
        "- apply: use knowledge in new situations\n"
        "- analyze: break down complex ideas\n"
        "- evaluate: judge and critique\n"
        "- create: synthesize new solutions\n\n"
        "Always provide clear problem statements and, when asked, detailed solutions.\n"
        "Adapt difficulty based on the student's mastery data if available."
    )
    model_preference = "large"

    def build_system_prompt(self, ctx: AgentContext) -> str:
        # Base class handles: profile, scene behavior, preferences, memories, RAG
        base = super().build_system_prompt(ctx)

        parts = [base]
        parts.append(
            "\nOutput format: Present each question clearly numbered. "
            "If multiple choice, label options A/B/C/D. "
            "Include the answer and brief explanation after each question."
        )

        return "\n".join(parts)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client()
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
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
