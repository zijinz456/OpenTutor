"""Task type definitions, constants, and policy inference.

Extracted from tasks.py. Contains all TypedDict definitions, status constants,
dataclasses, and policy inference logic used across the activity subsystem.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NotRequired, TypedDict


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


@dataclass(frozen=True)
class TaskPolicy:
    requires_approval: bool
    task_kind: str
    risk_level: str
    approval_reason: str | None
    approval_action: str | None


JsonObject = dict[str, Any]


class GoalUpdatePayload(TypedDict):
    goal_id: str
    title: str
    status: str
    current_milestone: str | None
    next_action: str | None


class TaskFollowUpPayload(TypedDict, total=False):
    ready: bool
    label: str
    task_type: str
    title: str
    summary: str | None
    input_json: JsonObject
    plan_prompt: str | None


class TaskReviewPayload(TypedDict):
    status: str
    outcome: str
    blockers: list[str]
    next_recommended_action: str | None
    follow_up: TaskFollowUpPayload
    goal_update: GoalUpdatePayload | None


class TaskStepResult(TypedDict, total=False):
    step_index: int
    step_type: str
    title: str
    success: bool
    input_message: str
    tool_calls: list[JsonObject]
    output: str
    raw_output: str
    summary: str
    error: str | None
    verifier: Any
    verifier_diagnostics: JsonObject | None
    provenance: JsonObject | None
    retry_count: int
    agent: str | None


class TaskCheckpointPayload(TypedDict):
    last_completed_step_index: int | None
    last_success_summary: str | None
    active_step_index: int | None
    completed_step_count: int
    failed_step_count: int
    resume_from_step_index: int
    retry_counts: dict[str, int]


class PlanProgressStep(TypedDict):
    step_index: int
    step_type: str
    title: str
    status: str
    depends_on: list[int]
    summary: str | None
    agent: str | None


class PlanResultPayload(TypedDict):
    steps: list[TaskStepResult]
    completed: int
    failed: int
    total: int
    resume_available: bool
    active_step_index: NotRequired[int]


class SerializedTaskPayload(TypedDict):
    id: str
    user_id: str
    course_id: str | None
    goal_id: str | None
    task_type: str
    status: str
    title: str
    summary: str | None
    source: str
    input_json: JsonObject | None
    metadata_json: JsonObject | None
    result_json: JsonObject | None
    error_message: str | None
    attempts: int
    max_attempts: int
    requires_approval: bool
    task_kind: str
    risk_level: str
    approval_status: str
    approval_reason: str | None
    approval_action: str | None
    checkpoint_json: TaskCheckpointPayload | None
    step_results: list[TaskStepResult]
    step_results_json: list[TaskStepResult]
    provenance: JsonObject | None
    provenance_json: JsonObject | None
    approved_at: str | None
    started_at: str | None
    cancel_requested_at: str | None
    created_at: str | None
    updated_at: str | None
    completed_at: str | None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def infer_task_policy(
    task_type: str,
    input_json: JsonObject | None = None,
    requires_approval: bool = False,
    *,
    title: str | None = None,
) -> TaskPolicy:
    """Infer the task policy (kind, risk, approval) from the task type and input."""
    payload = input_json or {}
    task_kind = TASK_KIND_READ_ONLY
    policy_requires_approval = False
    risk_level = "low"
    approval_reason: str | None = None
    approval_action: str | None = None

    if task_type == "code_execution":
        persistent_execution = any(
            _truthy(payload.get(key))
            for key in ("persist", "file_output", "write_files", "save_results", "write_to_workspace")
        ) or any(payload.get(key) for key in ("output_path", "save_path", "workspace_path", "filename"))
        if persistent_execution:
            task_kind = TASK_KIND_EXTERNAL
            policy_requires_approval = True
            risk_level = "high"
            approval_reason = "This code execution can persist output or write files outside the transient sandbox."
            approval_action = "Run Python code and write generated files or persisted outputs."
        else:
            task_kind = TASK_KIND_READ_ONLY
            risk_level = "low"
    elif task_type in {"notification_dispatch", "push_notification", "channel_send"}:
        task_kind = TASK_KIND_NOTIFICATION
        policy_requires_approval = True
        risk_level = "medium"
        approval_reason = "This task will send a notification outside the current workspace."
        approval_action = "Dispatch a notification to a configured delivery channel."
    elif task_type in {"external_web_action", "web_action", "browser_action"}:
        task_kind = TASK_KIND_EXTERNAL
        policy_requires_approval = True
        risk_level = "high"
        approval_reason = "This task would trigger an external web action."
        approval_action = "Perform an outbound web or browser action."
    elif task_type in {"semester_init", "generate_quiz", "create_flashcard", "create_flashcards"}:
        task_kind = TASK_KIND_CONTENT_MUTATION
        risk_level = "medium" if requires_approval else "low"

    resolved_requires_approval = bool(requires_approval or policy_requires_approval)
    if resolved_requires_approval and approval_reason is None:
        approval_reason = "This task was explicitly marked as requiring manual approval before execution."
    if resolved_requires_approval and approval_action is None:
        approval_action = f"Execute task '{title or task_type}' and persist its results."
    if resolved_requires_approval and risk_level == "low":
        risk_level = "medium"

    return TaskPolicy(
        requires_approval=resolved_requires_approval,
        task_kind=task_kind,
        risk_level=risk_level,
        approval_reason=approval_reason,
        approval_action=approval_action,
    )


def normalize_task_status(status: str | None) -> str:
    if status == LEGACY_APPROVAL_REQUIRED_STATUS:
        return APPROVAL_REQUIRED_STATUS
    if status == "retrying":
        return "queued"
    return status or "queued"


def infer_task_kind(task_type: str, input_json: JsonObject | None = None) -> str:
    return infer_task_policy(task_type, input_json).task_kind


def infer_risk_level(task_kind: str, requires_approval: bool, task_type: str) -> str:
    policy_risk = infer_task_policy(task_type, requires_approval=requires_approval).risk_level
    if policy_risk != "low":
        return policy_risk
    if task_kind == TASK_KIND_EXTERNAL:
        return "high"
    if requires_approval or task_kind in {TASK_KIND_NOTIFICATION, TASK_KIND_CONTENT_MUTATION}:
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
