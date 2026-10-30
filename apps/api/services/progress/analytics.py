"""Progress analytics — course-level summaries and error pattern analysis.

Split from tracker.py to separate analytics queries from core mastery tracking.
"""

import uuid
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


async def get_course_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Get overall progress for a course (see services.progress.summary)."""
    from services.progress.summary import course_summary

    return await course_summary(db, user_id, course_id)


async def get_error_pattern_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    limit: int = 5,
) -> list[dict]:
    """Return top error categories by frequency for a user+course.

    Aggregates unmastered WrongAnswer entries grouped by error_category.
    Returns: [{"category": str, "count": int, "percentage": float}]
    """
    from models.ingestion import WrongAnswer

    result = await db.execute(
        select(WrongAnswer.error_category, func.count(WrongAnswer.id).label("cnt"))
        .where(
            WrongAnswer.user_id == user_id,
            WrongAnswer.course_id == course_id,
            WrongAnswer.mastered.is_(False),
            WrongAnswer.error_category.isnot(None),
        )
        .group_by(WrongAnswer.error_category)
        .order_by(func.count(WrongAnswer.id).desc())
        .limit(limit)
    )
    rows = result.all()
    total = sum(r.cnt for r in rows)
    return [
        {
            "category": r.error_category,
            "count": r.cnt,
            "percentage": round(r.cnt / max(total, 1) * 100, 1),
        }
        for r in rows
    ]
