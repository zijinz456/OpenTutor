"""ReviewAgent — handles REVIEW intent for error analysis and answer feedback.

Borrows from:
- HelloAgents ReviewerAgent: structured review workflow
- Spec Section 5: WF-5 Wrong Answer Review workflow
- Spec Section 4.4: ErrorAnalyzer 5-category classification
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class ReviewAgent(BaseAgent):
    """Analyzes errors, provides feedback on wrong answers, and identifies knowledge gaps."""

    name = "review"
    profile = (
        "You are OpenTutor's Review Specialist.\n"
        "Analyze student errors using a 5-category classification:\n"
        "1. conceptual: Misunderstanding of core concepts\n"
        "2. procedural: Wrong steps or method application\n"
        "3. computational: Calculation or arithmetic errors\n"
        "4. reading: Misreading the question or data\n"
        "5. careless: Simple oversight or typo\n\n"
        "For each error:\n"
        "- Identify the error category\n"
        "- Explain WHY the mistake happened\n"
        "- Show the correct approach step by step\n"
        "- Suggest specific practice to prevent recurrence\n"
        "- Connect to relevant prerequisite knowledge if the error is conceptual\n\n"
        "Be encouraging but precise. Focus on understanding, not just correction."
    )
    model_preference = "large"

    def build_system_prompt(self, ctx: AgentContext) -> str:
        # Base class handles: profile, scene behavior, preferences, memories, RAG
        return super().build_system_prompt(ctx)

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
