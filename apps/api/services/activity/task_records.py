"""Task persistence and serialization helpers.

Keeps durable task record creation and API serialization separate from
task policy constants and review payload builders.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_task import AgentTask
from utils.serializers import serialize_model

from services.activity.task_review import (
    attach_task_review_payload,
    build_task_review_payload,
)
from services.activity.task_types import (
    APPROVAL_REQUIRED_STATUS,
    FINAL_TASK_STATUSES,
    JsonObject,
    TaskCheckpointPayload,
    SerializedTaskPayload,
    TaskStepResult,
    _truncate_summary,
    infer_approval_status,
    infer_task_policy,
    normalize_task_status,
)


def serialize_task(task: AgentTask) -> SerializedTaskPayload:
    """Serialize an AgentTask to a dict suitable for API responses."""
    normalized_status = normalize_task_status(task.status)
    approval_status = infer_approval_status(
        requires_approval=task.requires_approval,
        status=normalized_status,
        approved_at=task.approved_at,
    )
    step_results: list[TaskStepResult] = list(task.step_results_json or [])
    return serialize_model(
        task,
        extra={
            "status": normalized_status,
            "task_kind": task.task_kind,
            "risk_level": task.risk_level,
            "approval_status": approval_status,
            "approval_reason": task.approval_reason,
            "approval_action": task.approval_action,
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
    input_json: JsonObject | None = None,
    metadata_json: JsonObject | None = None,
    result_json: JsonObject | None = None,
    error_message: str | None = None,
    attempts: int = 0,
    max_attempts: int = 1,
    requires_approval: bool = False,
    task_kind: str | None = None,
    risk_level: str | None = None,
    approval_status: str | None = None,
    checkpoint_json: TaskCheckpointPayload | None = None,
    step_results_json: list[TaskStepResult] | None = None,
    provenance_json: JsonObject | None = None,
    approved_at: datetime | None = None,
    started_at: datetime | None = None,
    cancel_requested_at: datetime | None = None,
    approval_reason: str | None = None,
    approval_action: str | None = None,
) -> AgentTask:
    """Create and persist a new AgentTask with inferred policy."""
    normalized_status = normalize_task_status(status)
    policy = infer_task_policy(
        task_type,
        input_json=input_json,
        requires_approval=requires_approval,
        title=title,
    )
    effective_requires_approval = policy.requires_approval
    if normalized_status == "queued" and effective_requires_approval and approved_at is None:
        normalized_status = APPROVAL_REQUIRED_STATUS
    resolved_task_kind = task_kind or policy.task_kind
    resolved_risk_level = risk_level or policy.risk_level
    resolved_approval_status = approval_status or infer_approval_status(
        requires_approval=effective_requires_approval,
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
        requires_approval=effective_requires_approval,
        task_kind=resolved_task_kind,
        risk_level=resolved_risk_level,
        approval_status=resolved_approval_status,
        approval_reason=approval_reason or policy.approval_reason,
        approval_action=approval_action or policy.approval_action,
        checkpoint_json=checkpoint_json,
        step_results_json=step_results_json,
        provenance_json=provenance_json,
        approved_at=approved_at,
        started_at=started_at,
        cancel_requested_at=cancel_requested_at,
        completed_at=datetime.now(timezone.utc) if normalized_status in FINAL_TASK_STATUSES else None,
    )
    if normalized_status == "completed" and result_json is not None:
        task.result_json = attach_task_review_payload(
            result_json,
            build_task_review_payload(task, result_json, task.summary),
        )
    db.add(task)
    await db.flush()
    return task
