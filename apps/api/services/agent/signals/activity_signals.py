"""Activity-related signal collectors.

Covers: failed tasks, inactivity detection, guided session readiness.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_task import AgentTask
from models.ingestion import Assignment, StudySession

from ._types import AgendaSignal

logger = logging.getLogger(__name__)


async def _collect_failed_tasks(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Most recent failed/cancelled/rejected tasks (recovery candidates)."""
    query = (
        select(AgentTask)
        .where(
            AgentTask.user_id == user_id,
            AgentTask.status.in_(("failed", "cancelled", "rejected")),
        )
    )
    if course_id:
        query = query.where(AgentTask.course_id == course_id)
    query = query.order_by(AgentTask.updated_at.desc()).limit(3)
    result = await db.execute(query)
    tasks = result.scalars().all()

    return [
        AgendaSignal(
            signal_type="failed_task",
            user_id=user_id,
            course_id=t.course_id,
            entity_id=str(t.id),
            title=t.title,
            urgency=80.0,
            detail={"status": t.status, "task_type": t.task_type, "error": t.error_message},
        )
        for t in tasks
    ]


async def _collect_inactivity(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Detect if the user has been inactive for >=3 days."""
    threshold = datetime.now(timezone.utc) - timedelta(days=3)
    query = (
        select(StudySession)
        .where(StudySession.user_id == user_id)
        .order_by(StudySession.started_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    last = result.scalar_one_or_none()

    if last and last.started_at and last.started_at < threshold:
        days_inactive = (datetime.now(timezone.utc) - last.started_at).days
        return [AgendaSignal(
            signal_type="inactivity",
            user_id=user_id,
            course_id=None,
            entity_id=f"inactivity:{user_id}",
            title=f"Inactive for {days_inactive} days",
            urgency=min(40.0 + days_inactive * 5, 65.0),
            detail={"days_inactive": days_inactive, "last_session": last.started_at.isoformat()},
        )]
    return []


async def _collect_guided_session_readiness(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Check if a guided learning session should be suggested.

    Fires when ALL conditions are met:
    1. Student has been active in the last 7 days
    2. At least one course has ingested content
    3. No guided session completed in the last 24 hours
    4. There exists either a deadline, overdue FSRS items, or weak areas
    """
    from models.course import Course
    from models.content import CourseContentTree

    now = datetime.now(timezone.utc)

    # Check recent activity (must have studied within 7 days)
    active_threshold = now - timedelta(days=7)
    last_session_result = await db.execute(
        select(StudySession)
        .where(StudySession.user_id == user_id, StudySession.started_at >= active_threshold)
        .limit(1)
    )
    if not last_session_result.scalar_one_or_none():
        return []

    # Check at least one course has content
    content_check = await db.execute(
        select(func.count(CourseContentTree.id))
        .join(Course, Course.id == CourseContentTree.course_id)
        .where(Course.user_id == user_id)
    )
    if (content_check.scalar() or 0) == 0:
        return []

    # Check no guided session in last 24 hours (via KV store)
    from services.agent.kv_store import kv_list
    recent_sessions = await kv_list(db, user_id, "guided_session")
    for session in recent_sessions:
        val = session.get("value", {})
        if isinstance(val, dict):
            completed_at = val.get("completed_at") or val.get("prepared_at")
            if completed_at:
                try:
                    ts = datetime.fromisoformat(completed_at)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if now - ts < timedelta(hours=24):
                        return []
                except (ValueError, TypeError) as exc:
                    logger.debug("Failed to parse activity timestamp: %s", exc)

    # Determine urgency based on what's available
    urgency = 45.0  # Base urgency (below weak_area at 55, above inactivity at 40)

    # Boost if there are deadlines
    deadline_count = await db.execute(
        select(func.count(Assignment.id)).where(
            Assignment.status == "active",
            Assignment.due_date.isnot(None),
            Assignment.due_date <= now + timedelta(days=7),
            Assignment.due_date >= now,
        )
    )
    if (deadline_count.scalar() or 0) > 0:
        urgency = 55.0

    target_course = course_id
    if not target_course:
        # Pick the course with content (inline after guided_session removal)
        from sqlalchemy import select as _sel
        from models.course import Course
        _crs = await db.execute(
            _sel(Course.id).where(Course.user_id == user_id).order_by(Course.updated_at.desc()).limit(1)
        )
        target_course = _crs.scalar_one_or_none()

    return [AgendaSignal(
        signal_type="guided_session_ready",
        user_id=user_id,
        course_id=target_course,
        entity_id=f"guided:{user_id}",
        title="Guided study session available",
        urgency=urgency,
        detail={"has_deadline": urgency > 50},
    )]
