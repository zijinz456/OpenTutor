"""Learning progress tracker service.

Tracks progress at course → chapter → knowledge point granularity.
Updates mastery scores based on quiz results and study time.
"""

import uuid
import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.progress import LearningProgress
from models.content import CourseContentTree

logger = logging.getLogger(__name__)


async def get_or_create_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
) -> LearningProgress:
    """Get or create a progress entry for a content node."""
    query = select(LearningProgress).where(
        LearningProgress.user_id == user_id,
        LearningProgress.course_id == course_id,
    )
    if content_node_id:
        query = query.where(LearningProgress.content_node_id == content_node_id)
    else:
        query = query.where(LearningProgress.content_node_id.is_(None))

    result = await db.execute(query)
    progress = result.scalar_one_or_none()

    if not progress:
        progress = LearningProgress(
            user_id=user_id,
            course_id=course_id,
            content_node_id=content_node_id,
        )
        db.add(progress)
        await db.flush()

    return progress


async def update_study_time(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
    minutes: int,
) -> LearningProgress:
    """Record study time for a content node."""
    progress = await get_or_create_progress(db, user_id, course_id, content_node_id)
    progress.time_spent_minutes += minutes
    progress.last_studied_at = datetime.utcnow()

    if progress.status == "not_started":
        progress.status = "in_progress"

    return progress


async def update_quiz_result(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
    is_correct: bool,
) -> LearningProgress:
    """Update progress based on quiz result."""
    progress = await get_or_create_progress(db, user_id, course_id, content_node_id)
    progress.quiz_attempts += 1
    if is_correct:
        progress.quiz_correct += 1

    # Update mastery score (simple weighted average)
    if progress.quiz_attempts > 0:
        quiz_mastery = progress.quiz_correct / progress.quiz_attempts
        # Blend with existing mastery (weighted toward quizzes)
        progress.mastery_score = quiz_mastery * 0.7 + min(progress.time_spent_minutes / 60, 1.0) * 0.3

    # Update status
    if progress.mastery_score >= 0.8 and progress.quiz_attempts >= 3:
        progress.status = "mastered"
    elif progress.quiz_attempts > 0:
        progress.status = "reviewed"

    return progress


async def get_course_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Get overall progress for a course."""
    # Get all content nodes for the course
    nodes_result = await db.execute(
        select(func.count(CourseContentTree.id))
        .where(CourseContentTree.course_id == course_id)
    )
    total_nodes = nodes_result.scalar() or 0

    # Get progress entries
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
    }
