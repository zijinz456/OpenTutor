"""Task submission, claiming, and queue queries."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session
from libs.datetime_utils import utcnow as _utcnow
from models.agent_task import AgentTask
from services.activity.task_records import create_task
from services.activity.task_types import (
    APPROVAL_REQUIRED_STATUS,
    EXECUTABLE_TASK_STATUSES,
    JsonObject,
    infer_approval_status,
)
from services.activity.redis_notify import notify_task_ready
from services.activity.engine_helpers import _refresh_task_policy
from services.activity.engine_lifecycle import _record_task_audit, _task_session
from services.activity.engine_execution import execute_task

logger = logging.getLogger(__name__)


async def submit_task(
    *,
    user_id: uuid.UUID,
    task_type: str,
    title: str,
    db: AsyncSession | None = None,
    course_id: uuid.UUID | None = None,
    goal_id: uuid.UUID | None = None,
    summary: str | None = None,
    source: str = "workflow",
    input_json: JsonObject | None = None,
    metadata_json: JsonObject | None = None,
    requires_approval: bool = False,
    max_attempts: int = 2,
) -> AgentTask:
    async with _task_session(db) as db_session:
        task = await create_task(
            db_session,
            user_id=user_id,
            course_id=course_id,
            goal_id=goal_id,
            task_type=task_type,
            title=title,
            summary=summary,
            status="queued",
            source=source,
            input_json=input_json,
            metadata_json=metadata_json,
            requires_approval=requires_approval,
            max_attempts=max_attempts,
        )
        await _record_task_audit(
            db_session,
            task,
            action_kind="task_submit",
            outcome="queued" if task.status != APPROVAL_REQUIRED_STATUS else "pending_approval",
        )
        await db_session.commit()
        await db_session.refresh(task)

        # Notify the activity engine via Redis (if enabled) so it wakes up
        # immediately instead of waiting for the next polling interval.
        if settings.activity_use_redis_notify and task.status != APPROVAL_REQUIRED_STATUS:
            await notify_task_ready(str(task.id))

        # Notification dispatch removed (Phase 1.1 refactor)
        if task.status == APPROVAL_REQUIRED_STATUS:
            logger.info("Task %s needs approval: %s", task.id, title)

        return task


async def _claim_pending_tasks(limit: int) -> list[uuid.UUID]:
    """Claim up to *limit* executable tasks atomically, returning their IDs."""
    async with async_session() as db:
        result = await db.execute(
            select(AgentTask)
            .where(
                AgentTask.status.in_(tuple(EXECUTABLE_TASK_STATUSES)),
                or_(AgentTask.requires_approval.is_(False), AgentTask.approved_at.is_not(None)),
                AgentTask.cancel_requested_at.is_(None),
            )
            .order_by(AgentTask.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        tasks = result.scalars().all()
        if not tasks:
            return []
        now = _utcnow()
        ids: list[uuid.UUID] = []
        for task in tasks:
            _refresh_task_policy(task)
            task.status = "running"
            task.approval_status = infer_approval_status(
                requires_approval=task.requires_approval,
                status=task.status,
                approved_at=task.approved_at,
            )
            task.started_at = now
            task.attempts += 1
            await _record_task_audit(db, task, action_kind="task_execute_start", outcome="running")
            ids.append(task.id)
        await db.commit()
        return ids


async def drain_once() -> bool:
    """Claim and execute a single task.  Kept for backward compatibility."""
    ids = await _claim_pending_tasks(1)
    if not ids:
        return False
    await execute_task(ids[0])
    return True
