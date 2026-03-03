"""Learning report generator — daily briefs and weekly summaries.

Generates personalised learning reports by aggregating data from multiple
services (progress, FSRS, goals, memory) and formatting via LLM.

Scheduler jobs call ``generate_daily_brief()`` and ``generate_weekly_report()``
which return markdown-formatted reports.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Float, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DAILY_BRIEF_PROMPT = """\
You are a personal study assistant generating a morning learning brief.
Keep it concise, encouraging, and actionable.

Format as a short morning brief (under 200 words):
1. Quick wins from yesterday (if any)
2. Today's priorities (what to study, what's due)
3. Review reminder (if items are overdue)
4. One motivational insight

Use friendly, casual tone. No headers longer than 3 words.
"""

WEEKLY_REPORT_PROMPT = """\
You are a personal study assistant generating a weekly learning summary.
Be specific with numbers and honest about areas needing improvement.

Format as a weekly report (under 400 words):
1. This Week's Highlights — what went well
2. By the Numbers — study time, quizzes taken, accuracy, reviews completed
3. Knowledge Growth — topics where mastery improved
4. Areas to Focus — topics that need more work
5. Next Week's Suggestions — 2-3 concrete actions

Use a supportive, data-driven tone.
"""


async def _gather_report_data(
    user_id: uuid.UUID,
    db: AsyncSession,
    days: int = 1,
) -> dict:
    """Gather learning data for the report period."""
    from models.ingestion import StudySession, WrongAnswer
    from models.practice import PracticeResult
    from models.progress import LearningProgress
    from models.study_goal import StudyGoal

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    # Study sessions in period
    sessions_result = await db.execute(
        select(func.count(StudySession.id), func.sum(StudySession.duration_minutes))
        .where(
            StudySession.user_id == user_id,
            StudySession.started_at >= cutoff,
        )
    )
    session_row = sessions_result.one()
    session_count = session_row[0] or 0
    total_minutes = session_row[1] or 0

    # Practice results (is_correct is boolean; cast to float for avg)
    practice_result = await db.execute(
        select(
            func.count(PracticeResult.id),
            func.avg(cast(PracticeResult.is_correct, Float)),
        )
        .where(
            PracticeResult.user_id == user_id,
            PracticeResult.answered_at >= cutoff,
        )
    )
    practice_row = practice_result.one()
    problems_attempted = practice_row[0] or 0
    avg_score = float(practice_row[1]) if practice_row[1] else 0.0

    # Overdue review items
    overdue_result = await db.execute(
        select(func.count(LearningProgress.id))
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.next_review_at.isnot(None),
            LearningProgress.next_review_at <= now,
            LearningProgress.mastery_score < 0.9,
        )
    )
    overdue_count = overdue_result.scalar() or 0

    # Active goals
    goals_result = await db.execute(
        select(StudyGoal)
        .where(StudyGoal.user_id == user_id, StudyGoal.status == "active")
        .order_by(StudyGoal.updated_at.desc())
        .limit(5)
    )
    goals = goals_result.scalars().all()
    goals_data = []
    for g in goals:
        days_left = None
        if g.target_date:
            target = g.target_date.replace(tzinfo=timezone.utc) if g.target_date.tzinfo is None else g.target_date
            days_left = max((target - now).days, 0)
        goals_data.append({
            "title": g.title,
            "next_action": g.next_action,
            "days_until_target": days_left,
        })

    # Unmastered wrong answers
    wrong_result = await db.execute(
        select(func.count(WrongAnswer.id))
        .where(WrongAnswer.user_id == user_id, WrongAnswer.mastered.is_(False))
    )
    unmastered_count = wrong_result.scalar() or 0

    # Mastery improvements in period — join with content tree for titles
    from models.content import CourseContentTree

    mastery_result = await db.execute(
        select(LearningProgress, CourseContentTree.title)
        .outerjoin(CourseContentTree, LearningProgress.content_node_id == CourseContentTree.id)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.updated_at >= cutoff,
            LearningProgress.mastery_score >= 0.7,
        )
        .order_by(LearningProgress.mastery_score.desc())
        .limit(5)
    )
    improved_rows = mastery_result.all()
    improved_topics = [
        {"title": title or "unknown", "mastery": float(p.mastery_score)}
        for p, title in improved_rows
    ]

    return {
        "period_days": days,
        "session_count": session_count,
        "total_study_minutes": total_minutes,
        "problems_attempted": problems_attempted,
        "average_score": round(avg_score, 2),
        "overdue_review_items": overdue_count,
        "unmastered_wrong_answers": unmastered_count,
        "active_goals": goals_data,
        "improved_topics": improved_topics,
    }


async def _save_report(
    db: AsyncSession,
    user_id: uuid.UUID,
    report_type: str,
    content: str,
    period_start: datetime,
    period_end: datetime,
    course_id: Optional[uuid.UUID] = None,
    data_snapshot: Optional[dict] = None,
):
    """Persist a generated report to the database and return the ORM instance."""
    from models.report import Report

    report = Report(
        user_id=user_id,
        course_id=course_id,
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        content=content,
        data_snapshot=data_snapshot,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


async def generate_daily_brief(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Generate a personalised daily learning brief.

    Returns markdown-formatted text.  Also persists the report to the
    ``reports`` table for archival.
    """
    from services.llm.router import get_llm_client

    days = 1
    data = await _gather_report_data(user_id, db, days=days)

    try:
        client = get_llm_client(tier="fast")
        report_text, _ = await client.chat(
            DAILY_BRIEF_PROMPT,
            json.dumps(data, default=str),
        )
    except Exception as e:
        logger.warning("Daily brief LLM failed: %s", e)
        report_text = _format_fallback_report(data, "daily")

    now = datetime.now(timezone.utc)
    try:
        await _save_report(
            db=db,
            user_id=user_id,
            report_type="daily_brief",
            content=report_text,
            period_start=now - timedelta(days=days),
            period_end=now,
            data_snapshot=data,
        )
    except Exception as e:
        logger.warning("Failed to persist daily brief: %s", e)

    return report_text


async def generate_weekly_report(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Generate a personalised weekly learning summary.

    Returns markdown-formatted text.  Also persists the report to the
    ``reports`` table for archival.
    """
    from services.llm.router import get_llm_client

    days = 7
    data = await _gather_report_data(user_id, db, days=days)

    try:
        client = get_llm_client(tier="standard")
        report_text, _ = await client.chat(
            WEEKLY_REPORT_PROMPT,
            json.dumps(data, default=str),
        )
    except Exception as e:
        logger.warning("Weekly report LLM failed: %s", e)
        report_text = _format_fallback_report(data, "weekly")

    now = datetime.now(timezone.utc)
    try:
        await _save_report(
            db=db,
            user_id=user_id,
            report_type="weekly_report",
            content=report_text,
            period_start=now - timedelta(days=days),
            period_end=now,
            data_snapshot=data,
        )
    except Exception as e:
        logger.warning("Failed to persist weekly report: %s", e)

    return report_text


def _format_fallback_report(data: dict, period: str) -> str:
    """Simple text fallback when LLM is unavailable."""
    lines = [f"## {'Daily Brief' if period == 'daily' else 'Weekly Summary'}\n"]

    if data["session_count"]:
        lines.append(f"- {data['session_count']} study sessions, {data['total_study_minutes']} minutes total")
    else:
        lines.append("- No study sessions recorded")

    if data["problems_attempted"]:
        lines.append(f"- {data['problems_attempted']} problems attempted (avg score: {data['average_score']:.0%})")

    if data["overdue_review_items"]:
        lines.append(f"- {data['overdue_review_items']} items overdue for review")

    if data["active_goals"]:
        lines.append("\n**Active Goals:**")
        for g in data["active_goals"][:3]:
            deadline = f" (due in {g['days_until_target']}d)" if g.get("days_until_target") is not None else ""
            lines.append(f"- {g['title']}{deadline}")

    return "\n".join(lines)
