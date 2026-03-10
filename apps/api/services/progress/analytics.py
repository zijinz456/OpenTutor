"""Progress analytics — course-level summaries and error pattern analysis.

Split from tracker.py to separate analytics queries from core mastery tracking.
"""

import uuid
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.progress import LearningProgress
from models.content import CourseContentTree

logger = logging.getLogger(__name__)


async def get_course_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Get overall progress for a course."""
    nodes_result = await db.execute(
        select(func.count(CourseContentTree.id))
        .where(CourseContentTree.course_id == course_id)
    )
    total_nodes = nodes_result.scalar() or 0

    progress_result = await db.execute(
        select(LearningProgress)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
        )
    )
    progress_entries = progress_result.scalars().all()

    mastered = sum(1 for p in progress_entries if p.status == "mastered")
    reviewed = sum(1 for p in progress_entries if p.status == "reviewed")
    in_progress = sum(1 for p in progress_entries if p.status == "in_progress")
    total_time = sum(p.time_spent_minutes for p in progress_entries)
    avg_mastery = (
        sum(p.mastery_score for p in progress_entries) / len(progress_entries)
        if progress_entries else 0.0
    )
    gap_type_breakdown: dict[str, int] = {}
    for entry in progress_entries:
        if entry.gap_type:
            gap_type_breakdown[entry.gap_type] = gap_type_breakdown.get(entry.gap_type, 0) + 1

    return {
        "course_id": str(course_id),
        "total_nodes": total_nodes,
        "mastered": mastered,
        "reviewed": reviewed,
        "in_progress": in_progress,
        "not_started": max(0, total_nodes - mastered - reviewed - in_progress),
        "total_study_minutes": total_time,
        "average_mastery": avg_mastery,
        "completion_percent": (mastered + reviewed) / max(total_nodes, 1) * 100,
        "gap_type_breakdown": gap_type_breakdown,
    }


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
