"""AssessmentAgent — comprehensive learning evaluation and progress reports.

Borrows from:
- MetaGPT qa_engineer.py: message-driven state machine + round limits
- HelloAgents ReviewerAgent: review feedback loop
- OpenAkita persona dimensions: multi-dimensional evaluation

Provides:
- Knowledge mastery assessment across topics
- Common error pattern analysis
- Study effort and consistency metrics
- Personalized improvement recommendations
- Exam readiness estimation
"""

import logging
from typing import AsyncIterator

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)


class AssessmentAgent(BaseAgent):
    """Generates comprehensive learning assessments and progress reports."""

    name = "assessment"
    profile = (
        "You are a learning assessment specialist.\n"
        "Evaluate student progress comprehensively:\n"
        "1. Knowledge mastery across topics\n"
        "2. Common error patterns and weak areas\n"
        "3. Study effort and consistency metrics\n"
        "4. Personalized improvement recommendations\n"
        "5. Exam readiness estimation\n"
        "Use data-driven insights, not just encouragement.\n"
        "Present results clearly with specific numbers and actionable suggestions."
    )
    model_preference = "large"

    async def _build_assessment_data(
        self, ctx: AgentContext, db: AsyncSession,
    ) -> str:
        """Collect learning data from multiple tables for assessment."""
        from models.progress import LearningProgress
        from models.ingestion import WrongAnswer, StudySession

        parts = []

        # 1. Learning progress per content node
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
            in_progress = sum(1 for p in progress if 0.2 <= p.mastery_score < 0.8)
            not_started = sum(1 for p in progress if p.mastery_score < 0.2)
            avg_mastery = sum(p.mastery_score for p in progress) / len(progress)
            total_time = sum(p.time_spent_minutes for p in progress)
            total_quizzes = sum(p.quiz_attempts for p in progress)
            total_correct = sum(p.quiz_correct for p in progress)

            parts.append(
                f"## Progress Overview\n"
                f"- Total topics: {len(progress)}\n"
                f"- Mastered (≥80%): {mastered}\n"
                f"- In progress (20-80%): {in_progress}\n"
                f"- Not started (<20%): {not_started}\n"
                f"- Average mastery: {avg_mastery:.1%}\n"
                f"- Total study time: {total_time} minutes\n"
                f"- Quiz attempts: {total_quizzes}, Correct: {total_correct}"
            )
        else:
            parts.append("## Progress Overview\nNo progress data available yet.")

        # 2. Recent wrong answers (error patterns)
        wrong_result = await db.execute(
            select(WrongAnswer)
            .where(
                WrongAnswer.user_id == ctx.user_id,
                WrongAnswer.course_id == ctx.course_id,
            )
            .order_by(WrongAnswer.created_at.desc())
            .limit(20)
        )
        wrong_answers = wrong_result.scalars().all()
        if wrong_answers:
            error_cats = {}
            for wa in wrong_answers:
                cat = wa.error_category or "unknown"
                error_cats[cat] = error_cats.get(cat, 0) + 1
            cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(error_cats.items(), key=lambda x: -x[1]))
            unmastered = sum(1 for wa in wrong_answers if not wa.mastered)
            parts.append(
                f"\n## Error Analysis\n"
                f"- Total wrong answers: {len(wrong_answers)}\n"
                f"- Unmastered: {unmastered}\n"
                f"- Error categories: {cat_str}"
            )
        else:
            parts.append("\n## Error Analysis\nNo wrong answers recorded.")

        # 3. Study sessions (effort & consistency)
        session_result = await db.execute(
            select(StudySession)
            .where(
                StudySession.user_id == ctx.user_id,
                StudySession.course_id == ctx.course_id,
            )
            .order_by(StudySession.started_at.desc())
            .limit(30)
        )
        sessions = session_result.scalars().all()
        if sessions:
            total_sessions = len(sessions)
            total_duration = sum(s.duration_minutes or 0 for s in sessions)
            total_problems = sum(s.problems_attempted for s in sessions)
            total_correct = sum(s.problems_correct for s in sessions)
            avg_duration = total_duration / total_sessions if total_sessions else 0

            parts.append(
                f"\n## Study Sessions (last {total_sessions})\n"
                f"- Total study time: {total_duration} minutes\n"
                f"- Average session: {avg_duration:.0f} minutes\n"
                f"- Problems attempted: {total_problems}\n"
                f"- Problems correct: {total_correct}\n"
                f"- Accuracy: {total_correct / total_problems:.1%}" if total_problems else ""
            )
        else:
            parts.append("\n## Study Sessions\nNo session data available.")

        return "\n".join(parts)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Generate comprehensive learning assessment."""
        assessment_data = await self._build_assessment_data(ctx, db)

        client = self.get_llm_client()
        system_prompt = self.build_system_prompt(ctx)
        system_prompt += f"\n\n{assessment_data}"

        ctx.response, _ = await client.chat(
            system_prompt,
            ctx.user_message,
        )
        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream assessment response."""
        ctx.delegated_agent = self.name
        ctx.transition(TaskPhase.REASONING)

        assessment_data = await self._build_assessment_data(ctx, db)

        system_prompt = self.build_system_prompt(ctx)
        system_prompt += f"\n\n{assessment_data}"

        client = self.get_llm_client()
        ctx.transition(TaskPhase.STREAMING)
        full_response = ""
        async for chunk in client.stream_chat(system_prompt, ctx.user_message):
            full_response += chunk
            yield chunk
        ctx.response = full_response
