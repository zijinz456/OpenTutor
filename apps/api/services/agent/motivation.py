"""MotivationAgent — learning encouragement and fatigue intervention.

Borrows from:
- OpenAkita persona.py: dimensionalized personality traits + proactive intervention engine
- OpenAkita handlers/persona.py: signal detection across multiple categories
- MetaGPT Role: profile-based behavior definition

Provides:
- Fatigue/frustration detection (regex + heuristic scoring)
- Genuine, progress-aware encouragement
- Practical suggestions (break, switch topic, easier problems)
- Milestone celebrations

This agent is NOT routed by IntentType — it intercepts via the Orchestrator
when fatigue signal exceeds threshold (0.6). See orchestrator.py.
"""

import logging
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class MotivationAgent(BaseAgent):
    """Intercepts high-fatigue messages with encouragement and practical advice."""

    name = "motivation"
    profile = (
        "You are a warm and encouraging learning companion.\n"
        "The student seems frustrated, tired, or demotivated.\n"
        "Respond with:\n"
        "- Genuine encouragement based on their actual progress (not generic platitudes)\n"
        "- Acknowledge what they've already accomplished\n"
        "- Practical suggestions: take a short break, switch to a different topic, "
        "try easier problems first, review what they already know\n"
        "- If they've been studying for a while, suggest a break with a specific return plan\n"
        "Be warm and supportive but not condescending. Be brief.\n"
        "After encouragement, gently redirect to productive learning if appropriate."
    )
    model_preference = "small"  # Doesn't need the largest model

    async def _get_recent_progress(self, ctx: AgentContext, db: AsyncSession) -> str:
        """Fetch recent study progress for personalized encouragement."""
        from models.ingestion import StudySession
        from models.progress import LearningProgress

        parts = []

        # Recent sessions
        session_result = await db.execute(
            select(StudySession)
            .where(StudySession.user_id == ctx.user_id)
            .order_by(StudySession.started_at.desc())
            .limit(5)
        )
        sessions = session_result.scalars().all()
        if sessions:
            total_time = sum(s.duration_minutes or 0 for s in sessions)
            total_problems = sum(s.problems_attempted for s in sessions)
            total_correct = sum(s.problems_correct for s in sessions)
            parts.append(
                f"Recent {len(sessions)} sessions: "
                f"{total_time} min studied, "
                f"{total_problems} problems attempted, "
                f"{total_correct} correct"
            )

        # Overall course progress
        if ctx.course_id:
            progress_result = await db.execute(
                select(LearningProgress)
                .where(
                    LearningProgress.user_id == ctx.user_id,
                    LearningProgress.course_id == ctx.course_id,
                )
            )
            progress = progress_result.scalars().all()
            if progress:
                mastered = sum(1 for p in progress if p.mastery_score >= 0.8)
                parts.append(f"Course progress: {mastered}/{len(progress)} topics mastered")

        return "; ".join(parts) if parts else "No recent study data available"

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate motivational response with progress context."""
        progress_summary = await self._get_recent_progress(ctx, db)
        fatigue = ctx.metadata.get("fatigue_level", 0.0)

        client = self.get_llm_client(ctx)
        system_prompt = self.build_system_prompt(ctx)
        system_prompt += (
            f"\n\n## Student Context:\n"
            f"- Fatigue level: {fatigue:.1f}/1.0\n"
            f"- Recent progress: {progress_summary}\n"
        )

        ctx.response, _ = await client.chat(system_prompt, ctx.user_message)
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream motivational response."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        progress_summary = await self._get_recent_progress(ctx, db)
        fatigue = ctx.metadata.get("fatigue_level", 0.0)

        system_prompt = self.build_system_prompt(ctx)
        system_prompt += (
            f"\n\n## Student Context:\n"
            f"- Fatigue level: {fatigue:.1f}/1.0\n"
            f"- Recent progress: {progress_summary}\n"
        )

        client = self.get_llm_client(ctx)
        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message):
            full_response += chunk
            yield chunk
        ctx.response = full_response
