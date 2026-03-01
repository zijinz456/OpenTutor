"""Helpers for durable task/activity records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_task import AgentTask
from utils.serializers import serialize_model


def _truncate_summary(summary: str | None, limit: int = 500) -> str | None:
    if not summary:
        return summary
    if len(summary) <= limit:
        return summary
    return summary[: limit - 3] + "..."


FINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "rejected"}
EXECUTABLE_TASK_STATUSES = {"queued", "resuming"}
APPROVAL_REQUIRED_STATUS = "pending_approval"
LEGACY_APPROVAL_REQUIRED_STATUS = "awaiting_approval"
CANCEL_REQUESTED_STATUS = "cancel_requested"
REJECTED_TASK_STATUS = "rejected"
RESUMING_TASK_STATUS = "resuming"
TASK_KIND_READ_ONLY = "read_only"
TASK_KIND_CONTENT_MUTATION = "content_mutation"
TASK_KIND_NOTIFICATION = "notification"
TASK_KIND_EXTERNAL = "external_side_effect"
APPROVAL_NOT_REQUIRED = "not_required"
APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"


def normalize_task_status(status: str | None) -> str:
    if status == LEGACY_APPROVAL_REQUIRED_STATUS:
        return APPROVAL_REQUIRED_STATUS
    if status == "retrying":
        return "queued"
    return status or "queued"


def infer_task_kind(task_type: str, input_json: dict[str, Any] | None = None) -> str:
    payload = input_json or {}
    if task_type == "code_execution":
        if payload.get("persist") or payload.get("file_output") or payload.get("write_files"):
            return TASK_KIND_EXTERNAL
        return TASK_KIND_EXTERNAL
    if task_type in {"semester_init"}:
        return TASK_KIND_CONTENT_MUTATION
    if task_type in {"notification_dispatch", "push_notification"}:
        return TASK_KIND_NOTIFICATION
    return TASK_KIND_READ_ONLY


def infer_risk_level(task_kind: str, requires_approval: bool, task_type: str) -> str:
    if task_type in {"code_execution", "semester_init"}:
        return "high"
    if requires_approval or task_kind in {TASK_KIND_NOTIFICATION, TASK_KIND_EXTERNAL}:
        return "medium"
    return "low"


def infer_approval_status(
    *,
    requires_approval: bool,
    status: str,
    approved_at: datetime | None,
) -> str:
    normalized_status = normalize_task_status(status)
    if not requires_approval:
        return APPROVAL_NOT_REQUIRED
    if normalized_status == REJECTED_TASK_STATUS:
        return APPROVAL_REJECTED
    if normalized_status == APPROVAL_REQUIRED_STATUS or approved_at is None:
        return APPROVAL_PENDING
    return APPROVAL_APPROVED


def serialize_task(task: AgentTask) -> dict[str, Any]:
    normalized_status = normalize_task_status(task.status)
    approval_status = infer_approval_status(
        requires_approval=task.requires_approval,
        status=normalized_status,
        approved_at=task.approved_at,
    )
    step_results = list(task.step_results_json or [])
    return serialize_model(
        task,
        extra={
            "status": normalized_status,
            "task_kind": task.task_kind,
            "risk_level": task.risk_level,
            "approval_status": approval_status,
            "checkpoint_json": task.checkpoint_json,
            "step_results": step_results,
            "step_results_json": step_results,
            "provenance": task.provenance_json,
            "provenance_json": task.provenance_json,
        },
    )


async def create_task(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    task_type: str,
    course_id: uuid.UUID | None = None,
    goal_id: uuid.UUID | None = None,
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
    task_kind: str | None = None,
    risk_level: str | None = None,
    approval_status: str | None = None,
    checkpoint_json: dict[str, Any] | None = None,
    step_results_json: list[dict[str, Any]] | None = None,
    provenance_json: dict[str, Any] | None = None,
    approved_at: datetime | None = None,
    started_at: datetime | None = None,
    cancel_requested_at: datetime | None = None,
) -> AgentTask:
    normalized_status = normalize_task_status(status)
    if normalized_status == "queued" and requires_approval and approved_at is None:
        normalized_status = APPROVAL_REQUIRED_STATUS
    resolved_task_kind = task_kind or infer_task_kind(task_type, input_json)
    resolved_risk_level = risk_level or infer_risk_level(resolved_task_kind, requires_approval, task_type)
    resolved_approval_status = approval_status or infer_approval_status(
        requires_approval=requires_approval,
        status=normalized_status,
        approved_at=approved_at,
    )
    task = AgentTask(
        user_id=user_id,
        course_id=course_id,
        goal_id=goal_id,
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
        task_kind=resolved_task_kind,
        risk_level=resolved_risk_level,
        approval_status=resolved_approval_status,
        checkpoint_json=checkpoint_json,
        step_results_json=step_results_json,
        provenance_json=provenance_json,
        approved_at=approved_at,
        started_at=started_at,
        cancel_requested_at=cancel_requested_at,
        completed_at=datetime.now(timezone.utc) if normalized_status in FINAL_TASK_STATUSES else None,
    )
    db.add(task)
    await db.flush()
    return task
