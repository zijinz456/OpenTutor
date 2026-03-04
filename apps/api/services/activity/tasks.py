"""Helpers for durable task/activity records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

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


def _extract_first_action(text: Any) -> str | None:
    if not isinstance(text, str) or not text.strip():
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


def _build_follow_up_payload(
    task: AgentTask,
    *,
    label: str,
    task_type: str,
    title: str,
    summary: str,
    input_json: JsonObject | None = None,
    plan_prompt: str | None = None,
) -> TaskFollowUpPayload:
    if not task.course_id:
        return {"ready": False, "label": label}

    payload: TaskFollowUpPayload = {
        "ready": True,
        "label": label,
        "task_type": task_type,
        "title": title[:200],
        "summary": _truncate_summary(summary, limit=300),
        "input_json": input_json or {"course_id": str(task.course_id)},
    }
    if plan_prompt:
        payload["plan_prompt"] = _truncate_summary(plan_prompt, limit=2000)
    return payload


def _step_title(step: TaskStepResult | JsonObject) -> str:
    return str(step.get("title") or f"Step {int(step.get('step_index') or 0) + 1}")


def build_task_review_payload(
    task: AgentTask,
    result_payload: JsonObject | None,
    summary: str | None,
    *,
    goal_update: GoalUpdatePayload | None = None,
) -> TaskReviewPayload:
    payload = result_payload or {}
    status = normalize_task_status(task.status)
    outcome = _truncate_summary(summary, limit=300) or task.title
    blockers: list[str] = []
    next_action = payload.get("next_action") if isinstance(payload.get("next_action"), str) else None
    follow_up: TaskFollowUpPayload = {"ready": False}

    if task.task_type == "multi_step":
        steps = payload.get("steps") if isinstance(payload.get("steps"), list) else []
        completed = int(payload.get("completed") or sum(1 for step in steps if step.get("success")))
        failed = int(payload.get("failed") or sum(1 for step in steps if not step.get("success")))
        total = int(payload.get("total") or len(steps) or max(completed + failed, 1))
        outcome = f"Completed {completed}/{total} planned step(s)."
        if failed:
            outcome = f"{outcome} {failed} step(s) still need attention."

        failed_steps = [step for step in steps if not step.get("success")]
        for step in failed_steps[:3]:
            title = str(step.get("title") or f"Step {int(step.get('step_index') or 0) + 1}")
            detail = str(step.get("error") or step.get("summary") or "Execution failed.")
            blockers.append(f"{title}: {_truncate_summary(detail, limit=180)}")

        if failed_steps:
            next_action = "Queue a tighter follow-up plan focused on the blocked steps."
            failed_lines = "\n".join(
                f"- {_step_title(step)}: "
                f"{_truncate_summary(str(step.get('summary') or step.get('error') or 'blocked'), limit=180)}"
                for step in failed_steps[:4]
            )
            follow_up = _build_follow_up_payload(
                task,
                label="Queue repair plan",
                task_type="multi_step",
                title=f"Repair plan: {task.title}",
                summary=next_action,
                input_json={"course_id": str(task.course_id)} if task.course_id else None,
                plan_prompt=(
                    f"The student completed the task '{task.title}' but some steps were blocked.\n"
                    f"Build a short follow-up study plan that repairs the blocked work and keeps momentum.\n\n"
                    f"Blocked steps:\n{failed_lines}"
                ),
            )
        else:
            next_action = next_action or "Queue the next measurable deliverable while this progress is fresh."
            completed_lines = "\n".join(
                f"- {_step_title(step)}: "
                f"{_truncate_summary(str(step.get('summary') or 'completed'), limit=180)}"
                for step in steps[:4]
                if step.get("success")
            ) or "- The previous plan completed successfully."
            follow_up = _build_follow_up_payload(
                task,
                label="Queue follow-up",
                task_type="multi_step",
                title=f"Follow-up: {task.title}",
                summary=next_action,
                input_json={"course_id": str(task.course_id)} if task.course_id else None,
                plan_prompt=(
                    f"The student completed the durable task '{task.title}'. "
                    f"Build the next concrete study task based on the finished work.\n\n"
                    f"Completed steps:\n{completed_lines}"
                ),
            )
    elif task.task_type == "weekly_prep":
        stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
        deadline_count = len(payload.get("deadlines") or [])
        session_count = int(stats.get("sessions_count") or 0)
        outcome = f"Weekly prep refreshed with {deadline_count} deadline(s) and {session_count} recent study session(s)."
        if session_count == 0:
            blockers.append("No study sessions were recorded in the last week.")
        next_action = next_action or _extract_first_action(payload.get("plan")) or "Queue the first concrete study block from this plan."
        follow_up = _build_follow_up_payload(
            task,
            label="Queue first task",
            task_type="multi_step",
            title=f"Execute weekly priority: {task.title}",
            summary=next_action,
            input_json={"course_id": str(task.course_id)} if task.course_id else None,
            plan_prompt=(
                f"Turn this weekly study plan into the first concrete durable task.\n\n"
                f"Plan:\n{payload.get('plan') or ''}\n\n"
                f"Recommended next action: {next_action}"
            ),
        )
    elif task.task_type == "exam_prep":
        readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
        days_until_exam = int(payload.get("days_until_exam") or 0)
        course_name = str(payload.get("course") or "the course")
        outcome = (
            f"Exam prep plan generated for {course_name}."
            if days_until_exam <= 0
            else f"Exam prep plan generated for {course_name} with {days_until_exam} day(s) remaining."
        )
        weak_areas = int(readiness.get("unmastered_wrong_answers") or 0)
        if weak_areas > 0:
            blockers.append(f"{weak_areas} unmastered wrong-answer area(s) still need review.")
        next_action = next_action or _extract_first_action(payload.get("plan")) or "Start the highest-priority study block from this exam plan."
        if weak_areas > 0:
            follow_up = _build_follow_up_payload(
                task,
                label="Queue targeted review",
                task_type="wrong_answer_review",
                title=f"Target weak areas: {task.title}",
                summary="Review the outstanding weak areas before the exam.",
                input_json={"course_id": str(task.course_id)} if task.course_id else None,
            )
        else:
            follow_up = _build_follow_up_payload(
                task,
                label="Queue study block",
                task_type="multi_step",
                title=f"Follow-up: {task.title}",
                summary=next_action,
                input_json={"course_id": str(task.course_id)} if task.course_id else None,
                plan_prompt=(
                    f"Turn this exam prep plan into the next concrete study task.\n\n"
                    f"Plan:\n{payload.get('plan') or ''}\n\n"
                    f"Recommended next action: {next_action}"
                ),
            )
    elif task.task_type == "assignment_analysis":
        title = str(payload.get("title") or task.title)
        relevant_content_count = int(payload.get("relevant_content_count") or 0)
        outcome = f"Assignment analysis completed for {title}."
        if relevant_content_count == 0:
            blockers.append("No relevant course materials were linked automatically.")
        next_action = next_action or "Queue a deliverable-by-deliverable assignment plan."
        follow_up = _build_follow_up_payload(
            task,
            label="Queue assignment plan",
            task_type="multi_step",
            title=f"Plan assignment: {title}",
            summary=next_action,
            input_json={"course_id": str(task.course_id)} if task.course_id else None,
            plan_prompt=(
                f"Convert this assignment analysis into a concrete execution plan.\n\n"
                f"Analysis:\n{payload.get('analysis') or ''}"
            ),
        )
    elif task.task_type == "wrong_answer_review":
        wrong_answer_count = int(payload.get("wrong_answer_count") or 0)
        outcome = f"Generated targeted review for {wrong_answer_count} wrong answer(s)."
        if wrong_answer_count == 0:
            blockers.append("No unresolved wrong answers were found.")
        next_action = next_action or (
            "Queue a corrective practice plan based on these mistakes."
            if wrong_answer_count > 0
            else "Choose the next study goal."
        )
        if wrong_answer_count > 0:
            follow_up = _build_follow_up_payload(
                task,
                label="Queue corrective plan",
                task_type="multi_step",
                title=f"Corrective plan: {task.title}",
                summary=next_action,
                input_json={"course_id": str(task.course_id)} if task.course_id else None,
                plan_prompt=(
                    f"Turn this wrong-answer review into a short corrective plan with practice and spaced review.\n\n"
                    f"Review:\n{payload.get('review') or ''}"
                ),
            )
    elif task.task_type == "code_execution":
        backend = str(payload.get("backend") or "sandbox")
        outcome = f"Code executed successfully in the {backend} runtime."
        next_action = "Inspect the output and decide whether another code iteration is needed."

    return {
        "status": status,
        "outcome": outcome,
        "blockers": blockers,
        "next_recommended_action": next_action,
        "follow_up": follow_up,
        "goal_update": goal_update,
    }


def attach_task_review_payload(
    result_payload: JsonObject | None,
    review_payload: TaskReviewPayload,
) -> JsonObject:
    payload = dict(result_payload or {})
    payload["task_review"] = review_payload
    return payload


def serialize_task(task: AgentTask) -> SerializedTaskPayload:
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
