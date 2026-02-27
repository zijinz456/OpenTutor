"""WF-2: Weekly Prep Workflow (Enhanced).

Flow: load_schedule → check_deadlines → summarize_progress → generate_plan

Reference from spec:
- WF-2 runs weekly to prepare study plans
- Checks upcoming deadlines (from assignments table)
- Reviews learning progress
- Generates prioritized weekly plan
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.ingestion import Assignment, StudySession
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


async def load_upcoming_deadlines(
    db: AsyncSession,
    user_id: uuid.UUID,
    days_ahead: int = 14,
) -> list[dict]:
    """Load assignments due in the next N days."""
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=days_ahead)

    # Get user's courses
    courses_result = await db.execute(
        select(Course).where(Course.user_id == user_id)
    )
    courses = courses_result.scalars().all()
    course_ids = [c.id for c in courses]

    if not course_ids:
        return []

    result = await db.execute(
        select(Assignment)
        .where(
            Assignment.course_id.in_(course_ids),
            Assignment.status == "active",
            Assignment.due_date.isnot(None),
            Assignment.due_date <= cutoff,
        )
        .order_by(Assignment.due_date)
    )
    assignments = result.scalars().all()

    course_map = {c.id: c.name for c in courses}

    return [
        {
            "title": a.title,
            "course": course_map.get(a.course_id, "Unknown"),
            "due_date": a.due_date.isoformat() if a.due_date else None,
            "type": a.assignment_type or "unknown",
            "days_until_due": (
                (
                    (a.due_date if a.due_date.tzinfo else a.due_date.replace(tzinfo=timezone.utc))
                    - now
                ).days
                if a.due_date
                else None
            ),
        }
        for a in assignments
    ]


async def get_recent_study_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    days_back: int = 7,
) -> dict:
    """Get study statistics from the past week."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)

    result = await db.execute(
        select(StudySession)
        .where(
            StudySession.user_id == user_id,
            StudySession.started_at >= cutoff,
        )
    )
    sessions = result.scalars().all()

    total_minutes = sum(s.duration_minutes or 0 for s in sessions)
    total_problems = sum(s.problems_attempted or 0 for s in sessions)
    total_correct = sum(s.problems_correct or 0 for s in sessions)

    return {
        "sessions_count": len(sessions),
        "total_minutes": total_minutes,
        "problems_attempted": total_problems,
        "problems_correct": total_correct,
        "accuracy": total_correct / max(total_problems, 1),
    }


async def run_weekly_prep(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Execute WF-2: Weekly prep workflow.

    Steps:
    1. Load upcoming deadlines
    2. Get recent study stats
    3. Generate weekly plan via LLM
    """
    deadlines = await load_upcoming_deadlines(db, user_id)
    stats = await get_recent_study_stats(db, user_id)

    # Get courses for coverage info
    courses_result = await db.execute(
        select(Course).where(Course.user_id == user_id)
    )
    courses = courses_result.scalars().all()

    # Build context for LLM
    deadline_text = "\n".join(
        f"- [{d['type']}] {d['course']}: {d['title']} (due in {d['days_until_due']} days)"
        for d in deadlines
    ) or "No upcoming deadlines."

    stats_text = (
        f"Last 7 days: {stats['sessions_count']} sessions, "
        f"{stats['total_minutes']} minutes studied, "
        f"{stats['problems_attempted']} problems ({stats['accuracy']:.0%} accuracy)"
    )

    client = get_llm_client()
    plan, _ = await client.chat(
        "You are a study planning assistant. Create actionable weekly plans based on deadlines and past performance.",
        f"""Create a study plan for the coming week.

## Upcoming Deadlines
{deadline_text}

## Last Week's Performance
{stats_text}

## Courses
{chr(10).join(f'- {c.name}' for c in courses)}

Create a day-by-day plan (Mon-Sun) that:
1. Prioritizes upcoming deadlines
2. Balances workload across days
3. Includes review sessions for weak areas
4. Is realistic (max 4-6 hours study per day)

Output in markdown format.""",
    )

    return {
        "deadlines": deadlines,
        "stats": stats,
        "plan": plan,
    }
