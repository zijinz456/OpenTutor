"""LayoutAgent — handles UI layout change requests (Phase 2 consolidation).

NEW agent. Parses user layout requests and emits [ACTION:update_layout:...]
markers. Does NOT use ReAct loop (no tool calling needed).
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


_LAYOUT_SYSTEM_PROMPT = """\
You are OpenTutor Zenus's Layout Manager.
You help users change the workspace layout by emitting action markers.

## Available Layout Presets
- balanced: Default 3-column layout (notes, chat, practice)
- notesFocused: Notes panel takes most space, smaller chat
- quizFocused: Practice/quiz panel takes most space
- chatFocused: Chat panel expanded, smaller side panels
- fullNotes: Notes panel fullscreen

## Available Sections
- notes: Study notes and course materials
- chat: Conversation with the tutor
- practice: Quiz, flashcards, and exercises
- canvas: Visual workspace
- plan: Study plan and goals

## Actions You Can Emit
- To change layout preset: [ACTION:set_layout_preset:<preset>]
- To show/hide a section: [ACTION:toggle_section:<section>:<show|hide>]
- To switch scene mode: [ACTION:switch_scene:<scene_name>]

Available scenes: study_session, exam_prep, assignment, review_drill, note_organize

## Rules
1. Always emit the appropriate ACTION marker(s) for the user's request.
2. After the marker, briefly confirm what you changed.
3. If the request is ambiguous, pick the most sensible option and explain.
4. Keep responses very short (1-2 sentences after the action).
5. You can emit multiple actions if the user asks for compound changes.

## Examples
- "make chat bigger" → [ACTION:set_layout_preset:chatFocused]
- "hide flashcards" → [ACTION:toggle_section:practice:hide]
- "switch to exam prep" → [ACTION:switch_scene:exam_prep]
- "I want to focus on notes" → [ACTION:set_layout_preset:notesFocused]
"""


class LayoutAgent(BaseAgent):
    """Handles UI layout change requests without tool calling."""

    name = "layout"
    profile = _LAYOUT_SYSTEM_PROMPT
    model_preference = "small"  # Layout changes don't need a large model

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)

        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message, images=ctx.images or None):
            full_response += chunk
            yield chunk
        ctx.response = full_response
