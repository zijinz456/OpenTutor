"""ExerciseAgent — handles QUIZ intent for generating practice problems.

The output contract is aligned with the shared practice annotation pipeline so
generated questions can later be persisted without inventing a second metadata
schema.
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)

_LAYER_INSTRUCTION = """
When generating practice problems, organize them in 3 difficulty layers:

Layer 1 (Basic): Direct concept recall/comprehension. No tricks, simple context.
  Bloom's: remember, understand
Layer 2 (Standard): Applied knowledge, moderate complexity, standard variants.
  Bloom's: apply, analyze
Layer 3 (Advanced): Traps, distractors, edge cases, multi-step reasoning.
  Bloom's: evaluate, create

For EACH question, include structured metadata using this shared schema:
```json
{
  "question_type": "mc",
  "question": "...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "correct_answer": "A",
  "explanation": "...",
  "difficulty_layer": 1,
  "problem_metadata": {
    "core_concept": "...",
    "bloom_level": "remember",
    "potential_traps": [],
    "layer_justification": "Direct definition recall, no distractors",
    "skill_focus": "recall",
    "source_section": "section name"
  }
}
```

This metadata is critical. Be accurate:
- difficulty_layer must reflect actual cognitive demand, not just topic complexity
- potential_traps must list specific pitfalls (empty [] for Layer 1)
- core_concept must name the single most important concept being tested
- skill_focus must describe the learning action being tested
"""


class ExerciseAgent(BaseAgent):
    """Generates quizzes, exercises, and practice problems."""

    name = "exercise"
    profile = (
        "You are OpenTutor's Exercise Generator.\n"
        "Create practice problems tailored to the student's level and the course materials.\n"
        "Generate questions across 3 difficulty layers for diagnostic coverage.\n\n"
        "Always provide clear problem statements and, when asked, detailed solutions.\n"
        "Adapt difficulty based on the student's mastery data if available."
    )
    model_preference = "large"

    def build_system_prompt(self, ctx: AgentContext) -> str:
        # Base class handles: profile, scene behavior, preferences, memories, RAG
        base = super().build_system_prompt(ctx)

        parts = [base]
        parts.append(_LAYER_INSTRUCTION)

        # Inject adaptive difficulty guidance if available
        if hasattr(ctx, "difficulty_guidance") and ctx.difficulty_guidance:
            parts.append(ctx.difficulty_guidance)

        parts.append(
            "\nIf the user asks for a practice set that could be saved or reused, "
            "output a valid JSON array following the shared schema exactly. "
            "Otherwise you may present the questions in readable markdown, but keep "
            "the same conceptual fields in mind when choosing difficulty and traps."
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
