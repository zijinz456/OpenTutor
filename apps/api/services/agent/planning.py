"""PlanningAgent — handles PLAN intent for study plan generation.

Borrows from:
- HelloAgents PlannerAgent: structured planning workflow
- smart-planner: calendar-aware scheduling, deadline management
- Spec Section 5: create_study_plan tool
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext

logger = logging.getLogger(__name__)


class PlanningAgent(ReActMixin, BaseAgent):
    """Generates and adjusts study plans based on deadlines, mastery, and preferences."""

    name = "planning"
    profile = (
        "You are OpenTutor Zenus's Study Planner.\n"
        "Create actionable, realistic study plans based on:\n"
        "- Upcoming deadlines and exam dates\n"
        "- Student's current mastery levels\n"
        "- Available study time and preferences\n"
        "- Course material structure\n\n"
        "Plans should be:\n"
        "- Day-by-day with specific tasks\n"
        "- Prioritize weak areas and upcoming deadlines\n"
        "- Include review sessions (spaced repetition)\n"
        "- Realistic (don't overload any single day)\n"
        "- Output in clear markdown format"
    )
    model_preference = "large"
    react_tools = ["lookup_progress", "get_mastery_report", "get_course_outline", "list_study_goals", "list_assignments"]

    def build_system_prompt(self, ctx: AgentContext) -> str:
        # Use base class for scene-aware prompt, then append planning-specific context
        base = super().build_system_prompt(ctx)
        parts = [base]

        if ctx.content_docs:
            parts.append("\n## Course Structure:\n")
            for doc in ctx.content_docs:
                parts.append(f"- {doc.get('title', '')} (Level {doc.get('level', 0)})")

        return "\n".join(parts)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client()
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        async for chunk in ReActMixin.stream(self, ctx, db):
            yield chunk

        # Persist generated plan to StudyPlan table
        await self._save_plan(ctx, db)

    async def _save_plan(self, ctx: AgentContext, db: AsyncSession) -> None:
        """Persist the generated study plan for future reference."""
        if not ctx.response or len(ctx.response) < 50:
            return
        try:
            from models.study_plan import StudyPlan
            from services.generated_assets import save_generated_asset
            plan = StudyPlan(
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                name=ctx.user_message[:100],
                scene_id=ctx.scene,
                tasks={"markdown": ctx.response, "source_message": ctx.user_message},
            )
            db.add(plan)
            await save_generated_asset(
                db,
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                asset_type="study_plan",
                title=ctx.user_message[:100] or "Study Plan",
                content={"markdown": ctx.response},
                metadata={"scene_id": ctx.scene, "source_message": ctx.user_message},
            )
            await db.flush()
            logger.info("Study plan saved for user=%s course=%s", ctx.user_id, ctx.course_id)
        except Exception as e:
            logger.warning("Failed to save study plan: %s", e)
