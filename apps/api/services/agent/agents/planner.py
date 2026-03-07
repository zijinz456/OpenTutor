"""PlanAgent — study plan generation (Phase 2 consolidation).

Replaces: PlanningAgent. Essentially a rename with the same core logic.
"""

import logging
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext, InputRequirement

logger = logging.getLogger(__name__)


class PlanAgent(ReActMixin, BaseAgent):
    """Generates and adjusts study plans based on deadlines, mastery, and preferences."""

    name = "planner"
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
    react_tools = [
        "lookup_progress", "get_mastery_report", "get_course_outline",
        "list_study_goals", "list_assignments", "create_study_plan",
        "export_calendar", "write_file", "list_files", "update_workspace",
    ]

    def get_required_inputs(self) -> list[InputRequirement]:
        return [
            InputRequirement(
                key="deadline",
                question="When is your exam or assignment due?",
                options=["Within 1 week", "Within 2 weeks", "Within 1 month", "End of semester"],
                check=lambda ctx: (
                    any(kw in ctx.user_message.lower() for kw in [
                        "deadline", "due", "exam date", "by next", "week", "month",
                        "截止", "考试", "期末", "ddl",
                    ])
                    or "deadline" in ctx.clarify_inputs
                ),
            ),
            InputRequirement(
                key="study_hours",
                question="How many hours per day can you study?",
                options=["1-2 hours", "3-4 hours", "5+ hours", "Weekends only"],
                check=lambda ctx: (
                    any(kw in ctx.user_message.lower() for kw in [
                        "hour", "time", "available", "小时", "时间",
                    ])
                    or "study_hours" in ctx.clarify_inputs
                ),
            ),
        ]

    def build_system_prompt(self, ctx: AgentContext) -> str:
        base = super().build_system_prompt(ctx)
        parts = [base]

        if ctx.content_docs:
            parts.append("\n## Course Structure:\n")
            for doc in ctx.content_docs:
                parts.append(f"- {doc.get('title', '')} (Level {doc.get('level', 0)})")

        assignments = ctx.metadata.get("assignments", [])
        if assignments:
            parts.append("\n## Upcoming Deadlines:\n")
            for a in assignments:
                due = a.get("due_date", "No date")
                atype = a.get("assignment_type", "unknown")
                parts.append(f"- [{atype}] {a.get('title', 'Untitled')} — due {due}")

        return "\n".join(parts)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        system_prompt = self.build_system_prompt(ctx)
        client = self.get_llm_client(ctx)
        ctx.response, _ = await client.chat(system_prompt, ctx.user_message, images=ctx.images or None)
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
            logger.exception("Failed to save study plan: %s", e)
