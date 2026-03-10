"""Assessment data builder for TutorAgent."""

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext

logger = logging.getLogger(__name__)


async def build_assessment_data(ctx: AgentContext, db: AsyncSession) -> str:
    """Collect learning data from multiple tables for assessment context."""
    from models.progress import LearningProgress
    from models.practice import PracticeProblem
    from models.ingestion import WrongAnswer, StudySession

    parts: list[str] = []

    # 1. Learning progress
    try:
        progress_result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.user_id == ctx.user_id,
                LearningProgress.course_id == ctx.course_id,
            )
        )
        progress = progress_result.scalars().all()
        if progress:
            mastered = sum(1 for p in progress if p.mastery_score >= 0.8)
            in_progress_count = sum(1 for p in progress if 0.2 <= p.mastery_score < 0.8)
            not_started = sum(1 for p in progress if p.mastery_score < 0.2)
            avg_mastery = sum(p.mastery_score for p in progress) / len(progress)
            total_time = sum(p.time_spent_minutes for p in progress)
            total_quizzes = sum(p.quiz_attempts for p in progress)
            total_correct = sum(p.quiz_correct for p in progress)

            parts.append(
                f"## Progress Overview\n"
                f"- Total topics: {len(progress)}\n"
                f"- Mastered (>=80%): {mastered}\n"
                f"- In progress (20-80%): {in_progress_count}\n"
                f"- Not started (<20%): {not_started}\n"
                f"- Average mastery: {avg_mastery:.1%}\n"
                f"- Total study time: {total_time} minutes\n"
                f"- Quiz attempts: {total_quizzes}, Correct: {total_correct}"
            )

            gap_counts: dict[str, int] = defaultdict(int)
            for p in progress:
                if p.gap_type:
                    gap_counts[p.gap_type] += 1
            if gap_counts:
                gap_str = ", ".join(f"{k}: {v}" for k, v in sorted(gap_counts.items(), key=lambda x: -x[1]))
                parts.append(f"\n## Difficulty Layer Gap Analysis\n- Gap types: {gap_str}")
    except (SQLAlchemyError, ConnectionError, TimeoutError) as e:
        logger.exception("Assessment progress loading failed: %s", e)

    # 2. Error analysis
    try:
        wrong_result = await db.execute(
            select(WrongAnswer, PracticeProblem)
            .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
            .where(
                WrongAnswer.user_id == ctx.user_id,
                WrongAnswer.course_id == ctx.course_id,
                WrongAnswer.error_category.isnot(None),
            )
            .order_by(WrongAnswer.created_at.desc())
            .limit(50)
        )
        wrong_rows = wrong_result.all()
        if wrong_rows:
            error_cats: dict[str, int] = {}
            for wa, _ in wrong_rows:
                cat = wa.error_category or "unknown"
                error_cats[cat] = error_cats.get(cat, 0) + 1
            cat_str = ", ".join(f"{k}: {v}" for k, v in sorted(error_cats.items(), key=lambda x: -x[1]))
            unmastered = sum(1 for wa, _ in wrong_rows if not wa.mastered)
            parts.append(
                f"\n## Error Analysis\n"
                f"- Total wrong answers analyzed: {len(wrong_rows)}\n"
                f"- Unmastered: {unmastered}\n"
                f"- Error categories: {cat_str}"
            )
    except (SQLAlchemyError, ConnectionError, TimeoutError) as e:
        logger.exception("Assessment error loading failed: %s", e)

    # 3. Study sessions
    try:
        session_result = await db.execute(
            select(StudySession).where(
                StudySession.user_id == ctx.user_id,
                StudySession.course_id == ctx.course_id,
            ).order_by(StudySession.started_at.desc()).limit(30)
        )
        sessions = session_result.scalars().all()
        if sessions:
            total_sessions = len(sessions)
            total_duration = sum(s.duration_minutes or 0 for s in sessions)
            total_problems = sum(s.problems_attempted for s in sessions)
            total_correct_sess = sum(s.problems_correct for s in sessions)
            avg_duration = total_duration / total_sessions if total_sessions else 0
            parts.append(
                f"\n## Study Sessions (last {total_sessions})\n"
                f"- Total study time: {total_duration} minutes\n"
                f"- Average session: {avg_duration:.0f} minutes\n"
                f"- Problems attempted: {total_problems}\n"
                f"- Problems correct: {total_correct_sess}"
            )
    except (SQLAlchemyError, ConnectionError, TimeoutError) as e:
        logger.exception("Assessment session loading failed: %s", e)

    return "\n".join(parts) if parts else "No assessment data available yet."
