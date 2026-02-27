"""PreferenceAgent — handles PREFERENCE intent for preference changes.

Handles explicit preference change requests. For implicit preference detection,
the post-processing pipeline's signal extractor handles it asynchronously.

This agent provides a conversational interface for preference management.
"""

import json
import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class PreferenceAgent(BaseAgent):
    """Handles explicit preference changes and settings conversations."""

    name = "preference"
    profile = (
        "You are OpenTutor's Preference Manager.\n"
        "Help the student adjust their learning experience settings.\n\n"
        "Available preference dimensions:\n"
        "- note_format: bullet_point | table | mind_map | step_by_step | summary\n"
        "- detail_level: concise | balanced | detailed\n"
        "- language: en | zh | auto\n"
        "- explanation_style: formal | conversational | socratic | example_heavy\n"
        "- visual_preference: auto | text_heavy | diagram_heavy | mixed\n"
        "- quiz_difficulty: adaptive | easy | medium | hard\n"
        "- layout_preset: balanced | notesFocused | quizFocused | chatFocused | fullNotes\n\n"
        "When the user asks to change a setting:\n"
        "1. Output the appropriate action marker\n"
        "2. Confirm what was changed\n"
        "3. Briefly explain the effect\n\n"
        "Action marker format:\n"
        "- Layout: [ACTION:set_layout_preset:<preset>]\n"
        "- Preference: [ACTION:set_preference:<dimension>:<value>]"
    )
    model_preference = "small"  # Preference changes don't need a large model

    def build_system_prompt(self, ctx: AgentContext) -> str:
        base = super().build_system_prompt(ctx)
        if ctx.preferences:
            base += f"\nCurrent preferences: {json.dumps(ctx.preferences, ensure_ascii=False)}"
        return base

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
