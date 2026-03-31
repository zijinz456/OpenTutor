"""Task state mutations: approve, reject, cancel, resume, retry."""

from __future__ import annotations

import logging
import uuid

from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session
from libs.datetime_utils import utcnow as _utcnow
from models.agent_task import AgentTask
from services.activity.task_types import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_REQUIRED_STATUS,
    CANCEL_REQUESTED_STATUS,
    EXECUTABLE_TASK_STATUSES,
    REJECTED_TASK_STATUS,
    RESUMING_TASK_STATUS,
    JsonObject,
    infer_approval_status,
)
from services.activity.redis_notify import notify_task_ready
from services.activity.engine_helpers import (
    TaskMutationError,
    _queueable_status,
    _refresh_task_policy,
    _task_event,
)

logger = logging.getLogger(__name__)


async def _record_task_audit(
    db: AsyncSession,
    task: AgentTask,
    *,
    action_kind: str,
    outcome: str,
    details: JsonObject | None = None,
) -> None:
    """Audit logging stub -- audit system removed in Phase 1.3."""
    logger.debug(
        "Task audit: %s %s (task=%s, user=%s)",
        action_kind, outcome, task.id, task.user_id,
    )


@asynccontextmanager
async def _null_async_context(value: AsyncSession):
    yield value


@asynccontextmanager
async def _task_session(db: AsyncSession | None):
    owns_session = db is None
    session = db or async_session()
    async with (session if owns_session else _null_async_context(session)) as db_session:
        yield db_session


async def _get_user_task(db: AsyncSession, task_id: uuid.UUID, user_id: uuid.UUID) -> AgentTask | None:
    result = await db.execute(
        select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user_id)
    )
    task = result.scalar_one_or_none()
    if task:
        _refresh_task_policy(task)
    return task


async def _commit_refreshed_task(db: AsyncSession, task: AgentTask) -> AgentTask:
    await db.commit()
    await db.refresh(task)
    return task


async def approve_task(task_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession | None = None) -> AgentTask | None:
    async with _task_session(db) as db_session:
        task = await _get_user_task(db_session, task_id, user_id)
        if not task:
            return None
        if task.status != APPROVAL_REQUIRED_STATUS:
            raise TaskMutationError(f"Task cannot be approved from status '{task.status}'")
        task.approved_at = _utcnow()
        task.status = "queued"
        task.approval_status = APPROVAL_APPROVED
        task.error_message = None
        task.completed_at = None
        _task_event(task, "approved")
        await _record_task_audit(db_session, task, action_kind="task_approve", outcome="queued")
        result = await _commit_refreshed_task(db_session, task)
        if settings.activity_use_redis_notify:
            await notify_task_ready(str(task.id))
        return result


async def reject_task(task_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession | None = None) -> AgentTask | None:
    async with _task_session(db) as db_session:
        task = await _get_user_task(db_session, task_id, user_id)
        if not task:
            return None
        if task.status != APPROVAL_REQUIRED_STATUS:
            raise TaskMutationError(f"Task cannot be rejected from status '{task.status}'")
        now = _utcnow()
        task.status = REJECTED_TASK_STATUS
        task.approval_status = APPROVAL_REJECTED
        task.error_message = "Rejected before execution."
        task.completed_at = now
        task.approved_at = None
        _task_event(task, "rejected")
        await _record_task_audit(db_session, task, action_kind="task_reject", outcome="rejected")
        return await _commit_refreshed_task(db_session, task)


async def cancel_task(task_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession | None = None) -> AgentTask | None:
    async with _task_session(db) as db_session:
        task = await _get_user_task(db_session, task_id, user_id)
        if not task:
            return None
        now = _utcnow()
        if task.status in {"completed", "failed", "cancelled", REJECTED_TASK_STATUS}:
            raise TaskMutationError(f"Task cannot be cancelled from status '{task.status}'")
        task.cancel_requested_at = now
        if task.status in {"queued", RESUMING_TASK_STATUS, APPROVAL_REQUIRED_STATUS}:
            task.status = "cancelled"
            task.completed_at = now
            task.error_message = "Cancelled before execution."
            _task_event(task, "cancelled")
            await _record_task_audit(db_session, task, action_kind="task_cancel", outcome="cancelled")
        elif task.status == "running":
            task.status = CANCEL_REQUESTED_STATUS
            task.completed_at = None
            _task_event(task, "cancel_requested")
            await _record_task_audit(db_session, task, action_kind="task_cancel", outcome="cancel_requested")
        return await _commit_refreshed_task(db_session, task)


async def resume_task(task_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession | None = None) -> AgentTask | None:
    async with _task_session(db) as db_session:
        task = await _get_user_task(db_session, task_id, user_id)
        if not task:
            return None
        if task.status == CANCEL_REQUESTED_STATUS:
            raise TaskMutationError("Task cancellation is still in progress")
        if task.status != "cancelled":
            raise TaskMutationError(f"Task cannot be resumed from status '{task.status}'")
        task.error_message = None
        task.completed_at = None
        task.cancel_requested_at = None
        task.status = RESUMING_TASK_STATUS if (not task.requires_approval or task.approved_at is not None) else APPROVAL_REQUIRED_STATUS
        task.approval_status = (
            APPROVAL_APPROVED if task.status == RESUMING_TASK_STATUS and task.requires_approval else APPROVAL_PENDING
        ) if task.requires_approval else task.approval_status
        _task_event(task, "resumed")
        await _record_task_audit(db_session, task, action_kind="task_resume", outcome=task.status)
        result = await _commit_refreshed_task(db_session, task)
        if settings.activity_use_redis_notify and task.status in EXECUTABLE_TASK_STATUSES:
            await notify_task_ready(str(task.id))
        return result


async def retry_task(task_id: uuid.UUID, user_id: uuid.UUID, db: AsyncSession | None = None) -> AgentTask | None:
    async with _task_session(db) as db_session:
        task = await _get_user_task(db_session, task_id, user_id)
        if not task:
            return None
        if task.status in {"running", CANCEL_REQUESTED_STATUS}:
            raise TaskMutationError(f"Task cannot be retried from status '{task.status}'")
        if task.status not in {"failed", "cancelled", REJECTED_TASK_STATUS}:
            raise TaskMutationError(f"Task cannot be retried from status '{task.status}'")
        task.error_message = None
        task.result_json = None
        task.step_results_json = None
        task.checkpoint_json = None
        task.provenance_json = None
        task.summary = None
        task.started_at = None
        task.completed_at = None
        task.cancel_requested_at = None
        task.attempts = 0
        if task.requires_approval:
            task.approved_at = None
        task.status = _queueable_status(task)
        task.approval_status = infer_approval_status(
            requires_approval=task.requires_approval,
            status=task.status,
            approved_at=task.approved_at,
        )
        _task_event(task, "retried")
        await _record_task_audit(db_session, task, action_kind="task_retry", outcome=task.status)
        result = await _commit_refreshed_task(db_session, task)
        if settings.activity_use_redis_notify and task.status in EXECUTABLE_TASK_STATUSES:
            await notify_task_ready(str(task.id))
        return result
