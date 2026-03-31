"""Pure utility functions for the activity engine (no I/O, no DB)."""

from __future__ import annotations

import uuid
from typing import Any

from libs.datetime_utils import utcnow as _utcnow
from services.activity.task_types import (
    APPROVAL_REQUIRED_STATUS,
    GoalUpdatePayload,
    JsonObject,
    PlanProgressStep,
    PlanResultPayload,
    TaskCheckpointPayload,
    TaskStepResult,
    infer_approval_status,
    infer_task_policy,
    normalize_task_status,
)
from services.provenance import merge_provenance


class TaskMutationError(ValueError):
    """Raised when an agent task transition is invalid for the current state."""


class TaskCancelledError(RuntimeError):
    """Raised when a running task is cancelled with partial progress available."""

    def __init__(
        self,
        message: str = "Task cancelled by user.",
        *,
        result_payload: JsonObject | None = None,
        summary: str | None = None,
    ) -> None:
        super().__init__(message)
        self.result_payload = result_payload
        self.summary = summary


def _normalize_uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _queueable_status(task) -> str:
    if task.requires_approval and task.approved_at is None:
        return APPROVAL_REQUIRED_STATUS
    return "queued"


def _refresh_task_policy(task) -> None:
    policy = infer_task_policy(
        task.task_type,
        input_json=task.input_json,
        requires_approval=task.requires_approval,
        title=task.title,
    )
    task.requires_approval = policy.requires_approval
    task.task_kind = policy.task_kind
    task.risk_level = policy.risk_level
    task.approval_reason = policy.approval_reason
    task.approval_action = policy.approval_action
    task.status = normalize_task_status(task.status)
    task.approval_status = infer_approval_status(
        requires_approval=task.requires_approval,
        status=task.status,
        approved_at=task.approved_at,
    )


def _task_event(task, event: str, **details: Any) -> None:
    metadata = dict(task.metadata_json or {})
    history = list(metadata.get("status_history") or [])
    history.append(
        {
            "event": event,
            "status": task.status,
            "at": _utcnow().isoformat(),
            "details": details or None,
        }
    )
    metadata["status_history"] = history[-20:]
    task.metadata_json = metadata


def _task_audit_details(task, extra: JsonObject | None = None) -> JsonObject:
    details: JsonObject = {
        "task_type": task.task_type,
        "title": task.title,
        "status": task.status,
        "task_kind": task.task_kind,
        "risk_level": task.risk_level,
        "requires_approval": task.requires_approval,
        "approval_reason": task.approval_reason,
        "approval_action": task.approval_action,
        "source": task.source,
    }
    if extra:
        details.update(extra)
    return details


def _coerce_step_results(raw_steps: Any) -> list[TaskStepResult]:
    if not isinstance(raw_steps, list):
        return []
    normalized: list[TaskStepResult] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        if "step_index" not in item:
            continue
        normalized.append(item)
    normalized.sort(key=lambda item: int(item.get("step_index", 0)))
    return normalized


def _build_plan_result_payload(steps: list[JsonObject], results: list[TaskStepResult]) -> PlanResultPayload:
    completed = sum(1 for item in results if item.get("success"))
    failed = sum(1 for item in results if not item.get("success"))
    return {
        "steps": results,
        "completed": completed,
        "failed": failed,
        "total": len(steps),
        "resume_available": completed + failed < len(steps),
    }


def _build_plan_summary(steps: list[JsonObject], results: list[TaskStepResult]) -> str:
    payload = _build_plan_result_payload(steps, results)
    summary_parts = [f"{payload['completed']}/{payload['total']} steps completed"]
    if payload["failed"]:
        summary_parts.append(f"{payload['failed']} failed")
    if payload["resume_available"]:
        summary_parts.append("resume available")
    return "; ".join(summary_parts)


def _build_checkpoint(
    results: list[TaskStepResult],
    *,
    active_step_index: int | None = None,
) -> TaskCheckpointPayload:
    completed = [item for item in results if item.get("success")]
    failed = [item for item in results if not item.get("success")]
    last_success = completed[-1] if completed else None
    retry_counts: dict[str, int] = {}
    for item in results:
        retry_counts[str(item.get("step_index"))] = int(item.get("retry_count") or 0)
    return {
        "last_completed_step_index": last_success.get("step_index") if last_success else None,
        "last_success_summary": last_success.get("summary") if last_success else None,
        "active_step_index": active_step_index,
        "completed_step_count": len(completed),
        "failed_step_count": len(failed),
        "resume_from_step_index": active_step_index if active_step_index is not None else len(completed),
        "retry_counts": retry_counts,
    }


def _merge_step_provenance(results: list[TaskStepResult]) -> JsonObject | None:
    merged: JsonObject | None = None
    for item in results:
        provenance = item.get("provenance")
        if isinstance(provenance, dict):
            merged = merge_provenance(merged, provenance)
    return merged


def _extract_first_action(text: str | None) -> str | None:
    if not text:
        return None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("- ", "* ")):
            return line[2:].strip()[:200] or None
        if len(line) > 3 and line[0].isdigit() and line[1:3] == ". ":
            return line[3:].strip()[:200] or None
    return None


def _serialize_goal_update(goal) -> GoalUpdatePayload:
    return {
        "goal_id": str(goal.id),
        "title": goal.title,
        "status": goal.status,
        "current_milestone": goal.current_milestone,
        "next_action": goal.next_action,
    }


def _refresh_task_checkpoint(task, *, active_step_index: int | None = None) -> None:
    if task.step_results_json:
        task.checkpoint_json = _build_checkpoint(list(task.step_results_json), active_step_index=active_step_index)


def _build_plan_progress(
    steps: list[JsonObject],
    *,
    results: list[TaskStepResult] | None = None,
    active_step_index: int | None = None,
) -> list[PlanProgressStep]:
    result_map = {item["step_index"]: item for item in (results or [])}
    progress: list[PlanProgressStep] = []
    for step in steps:
        step_index = step["step_index"]
        result = result_map.get(step_index)
        status = "pending"
        if result is not None:
            status = "completed" if result.get("success") else "failed"
            if result.get("summary", "").startswith("Skipped"):
                status = "skipped"
        elif active_step_index == step_index:
            status = "running"
        progress.append(
            {
                "step_index": step_index,
                "step_type": step.get("step_type", "unknown"),
                "title": step.get("title", f"Step {step_index + 1}"),
                "status": status,
                "depends_on": step.get("depends_on", []),
                "summary": result.get("summary") if result else None,
                "agent": result.get("agent") if result else step.get("agent"),
            }
        )
    return progress


def _build_plan_result_snapshot(
    steps: list[JsonObject],
    results: list[TaskStepResult],
    *,
    active_step_index: int | None = None,
) -> PlanResultPayload:
    payload = _build_plan_result_payload(steps, results)
    if active_step_index is not None:
        payload["active_step_index"] = active_step_index
    return payload
