"""Helpers for durable task/activity records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_task import AgentTask


def _truncate_summary(summary: str | None, limit: int = 500) -> str | None:
    if not summary:
        return summary
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3] + "..."


FINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
EXECUTABLE_TASK_STATUSES = {"queued", "retrying"}
APPROVAL_REQUIRED_STATUS = "awaiting_approval"


def serialize_task(task: AgentTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "user_id": str(task.user_id),
        "course_id": str(task.course_id) if task.course_id else None,
        "task_type": task.task_type,
        "status": task.status,
        "title": task.title,
        "summary": task.summary,
        "source": task.source,
        "input_json": task.input_json,
        "metadata_json": task.metadata_json,
        "result_json": task.result_json,
        "error_message": task.error_message,
        "attempts": task.attempts,
        "max_attempts": task.max_attempts,
        "requires_approval": task.requires_approval,
        "approved_at": task.approved_at.isoformat() if task.approved_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "cancel_requested_at": task.cancel_requested_at.isoformat() if task.cancel_requested_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


async def create_task(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    task_type: str,
    course_id: uuid.UUID | None = None,
    status: str = "completed",
    summary: str | None = None,
    source: str = "workflow",
    input_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
    result_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    attempts: int = 0,
    max_attempts: int = 1,
    requires_approval: bool = False,
    approved_at: datetime | None = None,
    started_at: datetime | None = None,
    cancel_requested_at: datetime | None = None,
) -> AgentTask:
    normalized_status = status
    if normalized_status == "queued" and requires_approval and approved_at is None:
        normalized_status = APPROVAL_REQUIRED_STATUS
    task = AgentTask(
        user_id=user_id,
        course_id=course_id,
        task_type=task_type,
        status=normalized_status,
        title=title,
        summary=_truncate_summary(summary),
        source=source,
        input_json=input_json,
        metadata_json=metadata_json,
        result_json=result_json,
        error_message=error_message,
        attempts=attempts,
        max_attempts=max(1, max_attempts),
        requires_approval=requires_approval,
        approved_at=approved_at,
        started_at=started_at,
        cancel_requested_at=cancel_requested_at,
        completed_at=datetime.now(timezone.utc) if normalized_status in FINAL_TASK_STATUSES else None,
    )
    db.add(task)
    await db.flush()
    return task
