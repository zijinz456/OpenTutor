"""Background execution engine for durable agent tasks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session
from models.agent_task import AgentTask
from models.study_goal import StudyGoal
from services.agent.code_execution import pop_sandbox_backend_override, push_sandbox_backend_override
from services.activity.tasks import (
    APPROVAL_APPROVED,
    APPROVAL_PENDING,
    APPROVAL_REJECTED,
    APPROVAL_REQUIRED_STATUS,
    CANCEL_REQUESTED_STATUS,
    EXECUTABLE_TASK_STATUSES,
    GoalUpdatePayload,
    JsonObject,
    PlanProgressStep,
    PlanResultPayload,
    REJECTED_TASK_STATUS,
    RESUMING_TASK_STATUS,
    TaskCheckpointPayload,
    TaskStepResult,
    _truncate_summary,
    attach_task_review_payload,
    build_task_review_payload,
    create_task,
    infer_task_policy,
    infer_approval_status,
    normalize_task_status,
)
from services.activity.redis_notify import (
    close_redis as _close_redis_notify,
    notify_task_ready,
    wait_for_task_notification,
)
from services.provenance import build_provenance, merge_provenance

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
IDLE_INTERVAL_SECONDS = 2.0
MAX_IDLE_INTERVAL_SECONDS = 30.0
BACKOFF_MULTIPLIER = 1.5

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_worker_semaphore: asyncio.Semaphore | None = None
_inflight_tasks: set[asyncio.Task] = set()


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


from libs.datetime_utils import utcnow as _utcnow


def _normalize_uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _queueable_status(task: AgentTask) -> str:
    if task.requires_approval and task.approved_at is None:
        return APPROVAL_REQUIRED_STATUS
    return "queued"


def _refresh_task_policy(task: AgentTask) -> None:
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


def _task_event(task: AgentTask, event: str, **details: Any) -> None:
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


def _task_audit_details(task: AgentTask, extra: JsonObject | None = None) -> JsonObject:
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


async def _record_task_audit(
    db: AsyncSession,
    task: AgentTask,
    *,
    action_kind: str,
    outcome: str,
    details: JsonObject | None = None,
) -> None:
    """Audit logging stub — audit system removed in Phase 1.3."""
    logger.debug(
        "Task audit: %s %s (task=%s, user=%s)",
        action_kind, outcome, task.id, task.user_id,
    )


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


def _serialize_goal_update(goal: StudyGoal) -> GoalUpdatePayload:
    return {
        "goal_id": str(goal.id),
        "title": goal.title,
        "status": goal.status,
        "current_milestone": goal.current_milestone,
        "next_action": goal.next_action,
    }


async def _sync_goal_after_task_success(
    db: AsyncSession,
    task: AgentTask,
    result_payload: JsonObject,
) -> GoalUpdatePayload | None:
    if not task.goal_id:
        return None
    result = await db.execute(
        select(StudyGoal).where(StudyGoal.id == task.goal_id, StudyGoal.user_id == task.user_id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        return None

    metadata = dict(goal.metadata_json or {})
    metadata["last_task_id"] = str(task.id)
    metadata["last_task_type"] = task.task_type
    metadata["last_reviewed_at"] = _utcnow().isoformat()

    next_action = (
        result_payload.get("next_action")
        or _extract_first_action(result_payload.get("plan"))
        or _extract_first_action(result_payload.get("analysis"))
        or _extract_first_action(result_payload.get("review"))
        or goal.next_action
    )

    if task.task_type == "weekly_prep":
        week_start = (task.input_json or {}).get("week_start")
        if week_start:
            metadata["last_week_start"] = str(week_start)
        deadline_count = len(result_payload.get("deadlines") or [])
        metadata["last_deadline_count"] = deadline_count
        goal.current_milestone = f"Weekly review refreshed with {deadline_count} tracked deadlines"
    elif task.task_type == "multi_step":
        completed = int(result_payload.get("completed") or 0)
        total = int(result_payload.get("total") or 0)
        failed = int(result_payload.get("failed") or 0)
        if total > 0:
            goal.current_milestone = f"Completed {completed}/{total} planned steps" + (f" with {failed} blocked" if failed else "")
    elif task.task_type == "exam_prep":
        goal.current_milestone = "Exam prep plan refreshed"
    elif task.task_type == "assignment_analysis":
        goal.current_milestone = f"Assignment analysis ready: {task.title}"
    elif task.task_type == "wrong_answer_review":
        wrong_answer_count = int(result_payload.get("wrong_answer_count") or 0)
        goal.current_milestone = f"Reviewed {wrong_answer_count} wrong answer(s)"

    if next_action:
        goal.next_action = next_action

    goal.metadata_json = metadata
    return _serialize_goal_update(goal)


def _refresh_task_checkpoint(task: AgentTask, *, active_step_index: int | None = None) -> None:
    if task.step_results_json:
        task.checkpoint_json = _build_checkpoint(list(task.step_results_json), active_step_index=active_step_index)


@contextmanager
def _force_container_sandbox():
    token = push_sandbox_backend_override("container")
    try:
        yield
    finally:
        pop_sandbox_backend_override(token)


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
    from services.activity.tasks import create_task

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


async def execute_task(task_id: uuid.UUID) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        _refresh_task_policy(task)
        payload = task.input_json or {}

    try:
        result_payload, summary = await _dispatch_task(
            task_id=task_id,
            task_type=task.task_type,
            user_id=task.user_id,
            payload=payload,
        )
    except TaskCancelledError as exc:
        logger.info("Agent task cancelled: %s", task_id)
        return await _mark_task_cancelled(
            task_id,
            error_message=str(exc),
            result_payload=exc.result_payload,
            summary=exc.summary,
        )
    except Exception as exc:
        logger.exception("Agent task failed: %s (%s)", task_id, exc)
        return await _mark_task_failure(task_id, str(exc))

    return await _mark_task_success(task_id, result_payload=result_payload, summary=summary)


async def _mark_task_success(task_id: uuid.UUID, *, result_payload: JsonObject, summary: str | None) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        now = _utcnow()
        if task.cancel_requested_at is not None:
            task.status = "cancelled"
            task.completed_at = now
            task.error_message = "Cancelled before results were applied."
            task.approval_status = infer_approval_status(
                requires_approval=task.requires_approval,
                status=task.status,
                approved_at=task.approved_at,
            )
            _task_event(task, "cancelled")
            await _record_task_audit(db, task, action_kind="task_execute_cancelled", outcome="cancelled")
            await db.commit()
            return False
        task.status = "completed"
        goal_update = await _sync_goal_after_task_success(db, task, result_payload)
        stored_result = attach_task_review_payload(
            result_payload,
            build_task_review_payload(
                task,
                result_payload,
                summary,
                goal_update=goal_update,
            ),
        )
        task.summary = _truncate_summary(summary)
        task.result_json = stored_result
        metadata = dict(task.metadata_json or {})
        auto_repair_task_id = await _queue_auto_repair_follow_up(
            db,
            task,
            stored_result,
        )
        if auto_repair_task_id:
            metadata["auto_repair_task_id"] = auto_repair_task_id
            task_review = task.result_json.get("task_review") if isinstance(task.result_json, dict) else None
            follow_up = task_review.get("follow_up") if isinstance(task_review, dict) else None
            if isinstance(follow_up, dict):
                updated_follow_up = dict(follow_up)
                updated_follow_up["auto_queued"] = True
                updated_follow_up["queued_task_id"] = auto_repair_task_id
                updated_task_review = dict(task_review)
                updated_task_review["follow_up"] = updated_follow_up
                updated_result = dict(task.result_json)
                updated_result["task_review"] = updated_task_review
                task.result_json = updated_result
        task.metadata_json = metadata
        merged_provenance = merge_provenance(
            metadata.get("provenance") if isinstance(metadata.get("provenance"), dict) else None,
            result_payload.get("provenance") if isinstance(result_payload, dict) else None,
        )
        if merged_provenance:
            metadata["provenance"] = merged_provenance
            task.metadata_json = metadata
            task.provenance_json = merged_provenance
        _refresh_task_checkpoint(task)
        task.approval_status = infer_approval_status(
            requires_approval=task.requires_approval,
            status=task.status,
            approved_at=task.approved_at,
        )
        task.error_message = None
        task.completed_at = now
        _task_event(task, "completed")
        await _record_task_audit(
            db,
            task,
            action_kind="task_execute_complete",
            outcome="completed",
            details={"result_keys": sorted(result_payload.keys())[:12]},
        )
        await db.commit()
        return True


async def _queue_auto_repair_follow_up(
    db: AsyncSession,
    task: AgentTask,
    result_payload: JsonObject,
) -> str | None:
    """Automatically queue a durable repair plan for failed multi-step tasks."""
    if task.task_type != "multi_step" or task.source == "task_auto_repair":
        return None
    if not task.course_id:
        return None

    task_review = result_payload.get("task_review")
    if not isinstance(task_review, dict):
        return None
    follow_up = task_review.get("follow_up")
    if not isinstance(follow_up, dict) or not follow_up.get("ready"):
        return None
    if str(follow_up.get("task_type") or "").strip() != "multi_step":
        return None
    label = str(follow_up.get("label") or "").lower()
    if "repair" not in label:
        return None

    existing_auto_repair_id = (task.metadata_json or {}).get("auto_repair_task_id")
    if existing_auto_repair_id:
        return str(existing_auto_repair_id)

    input_json = dict(follow_up.get("input_json") or {})
    plan_prompt = str(follow_up.get("plan_prompt") or follow_up.get("summary") or follow_up.get("title") or "").strip()
    if "course_id" not in input_json:
        input_json["course_id"] = str(task.course_id)
    if not input_json.get("steps"):
        from services.agent.task_planner import create_plan

        try:
            steps = await create_plan(plan_prompt, task.user_id, task.course_id)
        except Exception as exc:
            logger.warning("Auto repair follow-up planning failed for task %s: %s", task.id, exc)
            return None
        input_json.update({
            "course_id": str(task.course_id),
            "steps": steps,
            "plan_prompt": plan_prompt,
        })

    queued = await create_task(
        db,
        user_id=task.user_id,
        course_id=task.course_id,
        goal_id=task.goal_id,
        task_type="multi_step",
        title=str(follow_up.get("title") or f"Repair plan: {task.title}")[:200],
        summary=str(follow_up.get("summary") or "Automatically queued repair plan.")[:300],
        status="queued",
        source="task_auto_repair",
        input_json=input_json,
        metadata_json={
            "parent_task_id": str(task.id),
            "parent_task_title": task.title,
            "trigger": "auto_repair_follow_up",
            "queue_label": follow_up.get("label"),
        },
        requires_approval=False,
        max_attempts=2,
    )
    await _record_task_audit(
        db,
        queued,
        action_kind="task_auto_follow_up_submit",
        outcome="queued",
        details={"parent_task_id": str(task.id)},
    )
    return str(queued.id)


async def _mark_task_cancelled(
    task_id: uuid.UUID,
    *,
    error_message: str,
    result_payload: JsonObject | None = None,
    summary: str | None = None,
) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        now = _utcnow()
        task.status = "cancelled"
        task.error_message = error_message
        task.summary = _truncate_summary(summary) or task.summary
        if result_payload is not None:
            task.result_json = result_payload
            result_provenance = result_payload.get("provenance") if isinstance(result_payload, dict) else None
            task.provenance_json = merge_provenance(task.provenance_json, result_provenance)
        _refresh_task_checkpoint(task)
        task.approval_status = infer_approval_status(
            requires_approval=task.requires_approval,
            status=task.status,
            approved_at=task.approved_at,
        )
        task.completed_at = now
        _task_event(task, "cancelled")
        await _record_task_audit(db, task, action_kind="task_execute_cancelled", outcome="cancelled")
        await db.commit()
        return True


async def _mark_task_failure(task_id: uuid.UUID, error_message: str) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        _refresh_task_policy(task)
        now = _utcnow()
        task.error_message = error_message
        task.completed_at = None
        if task.cancel_requested_at is not None:
            task.status = "cancelled"
            task.completed_at = now
            _task_event(task, "cancelled")
        elif task.attempts < max(task.max_attempts, 1):
            task.status = "queued"
            _task_event(task, "auto_retry_scheduled")
        else:
            task.status = "failed"
            task.completed_at = now
            _task_event(task, "failed")
        _refresh_task_checkpoint(task)
        task.approval_status = infer_approval_status(
            requires_approval=task.requires_approval,
            status=task.status,
            approved_at=task.approved_at,
        )
        await _record_task_audit(
            db,
            task,
            action_kind="task_execute_failed",
            outcome=task.status,
            details={"error_message": error_message},
        )
        await db.commit()
        return True


async def _dispatch_task(
    *,
    task_id: uuid.UUID,
    task_type: str,
    user_id: uuid.UUID,
    payload: JsonObject,
) -> tuple[JsonObject, str | None]:
    with _force_container_sandbox():
        async with async_session() as db:
            llm_task_labels = {
                "semester_init": "Semester initialization",
                "weekly_prep": "Weekly prep",
                "assignment_analysis": "Assignment analysis",
                "wrong_answer_review": "Wrong-answer review",
                "exam_prep": "Exam prep",
                "generate_quiz": "Quiz generation",
                "create_flashcard": "Flashcard generation",
                "create_flashcards": "Flashcard generation",
                "agent_subtask": "Agent task execution",
            }
            if task_type in llm_task_labels:
                from services.llm.readiness import ensure_llm_ready

                await ensure_llm_ready(llm_task_labels[task_type])

            if task_type == "weekly_prep":
                from services.workflow.weekly_prep import run_weekly_prep

                result = await run_weekly_prep(db, user_id)
                result["provenance"] = merge_provenance(
                    build_provenance(
                        workflow="weekly_prep",
                        generated=True,
                        source_labels=["workflow", "generated"],
                        scheduler_trigger=str(payload.get("trigger") or "") or None,
                    ),
                    result.get("provenance") if isinstance(result, dict) else None,
                )
                return result, (result.get("plan", "") or "Weekly plan generated.")[:300]

            if task_type == "exam_prep":
                from services.workflow.exam_prep import run_exam_prep

                course_id = _normalize_uuid(payload.get("course_id"))
                if not course_id:
                    raise ValueError("exam_prep requires course_id")
                result = await run_exam_prep(
                    db,
                    user_id,
                    course_id,
                    payload.get("exam_topic"),
                    int(payload.get("days_until_exam") or 7),
                )
                return result, (result.get("plan", "") or "Exam prep plan generated.")[:300]

            if task_type == "wrong_answer_review":
                from services.workflow.wrong_answer_review import run_wrong_answer_review

                result = await run_wrong_answer_review(db, user_id, _normalize_uuid(payload.get("course_id")))
                return result, (result.get("review", "") or "Wrong-answer review generated.")[:300]

            if task_type == "assignment_analysis":
                from services.workflow.assignment_analysis import run_assignment_analysis

                assignment_id = _normalize_uuid(payload.get("assignment_id"))
                if not assignment_id:
                    raise ValueError("assignment_analysis requires assignment_id")
                result = await run_assignment_analysis(db, user_id, assignment_id)
                if result.get("error"):
                    raise ValueError(str(result["error"]))
                return result, (result.get("analysis", "") or "Assignment analysis generated.")[:300]

            if task_type == "generate_quiz":
                from services.course_access import get_course_or_404
                from services.parser.quiz import extract_questions
                from services.search.hybrid import hybrid_search

                course_id = _normalize_uuid(payload.get("course_id"))
                if not course_id:
                    raise ValueError("generate_quiz requires course_id")

                query = str(payload.get("topic") or payload.get("description") or "key concepts").strip()
                count = min(max(int(payload.get("count") or 3), 1), 10)
                await get_course_or_404(db, course_id, user_id=user_id)
                results = await hybrid_search(db, course_id, query or "key concepts", limit=3)
                if not results:
                    return {
                        "problem_ids": [],
                        "count": 0,
                        "query": query,
                    }, "No course content found to generate questions from."

                content = "\n\n".join(str(item.get("content", ""))[:2000] for item in results)
                title = str(payload.get("title") or payload.get("description") or results[0].get("title") or "Course Content")
                problems = await extract_questions(content, title, course_id)
                persisted = problems[:count]
                for problem in persisted:
                    db.add(problem)
                await db.commit()
                return {
                    "problem_ids": [str(problem.id) for problem in persisted],
                    "count": len(persisted),
                    "query": query,
                }, f"Generated {len(persisted)} quiz question(s)."

            if task_type in {"create_flashcard", "create_flashcards"}:
                from services.course_access import get_course_or_404
                from services.generated_assets import save_generated_asset
                from services.spaced_repetition.flashcards import generate_flashcards

                course_id = _normalize_uuid(payload.get("course_id"))
                if not course_id:
                    raise ValueError("create_flashcard requires course_id")

                content_node_id = _normalize_uuid(payload.get("content_node_id"))
                count = min(max(int(payload.get("count") or 5), 1), 20)
                course = await get_course_or_404(db, course_id, user_id=user_id)
                cards = await generate_flashcards(db, course_id, content_node_id, count)
                batch = None
                if cards:
                    batch = await save_generated_asset(
                        db,
                        user_id=user_id,
                        course_id=course_id,
                        asset_type="flashcards",
                        title=str(payload.get("title") or course.name),
                        content={"cards": cards},
                        metadata={"count": len(cards), "source": "agent_task"},
                    )
                await db.commit()
                return {
                    "cards": cards,
                    "count": len(cards),
                    "batch_id": str(batch["batch_id"]) if batch else None,
                }, f"Generated {len(cards)} flashcard(s)."

            if task_type == "multi_step":
                return await _run_multi_step_plan(db, task_id, user_id, payload, async_session)

            if task_type == "chat_post_process":
                from services.agent.background_runtime import execute_post_process_task

                return await execute_post_process_task(payload, async_session)

            if task_type == "code_execution":
                from services.agent.code_execution import CodeExecutionAgent

                code = str(payload.get("code") or "")
                if not code.strip():
                    raise ValueError("code_execution requires non-empty code")
                agent = CodeExecutionAgent()
                safe, reason = agent._validate_code(code)
                if not safe:
                    raise ValueError(reason)
                result = await asyncio.to_thread(agent._execute_safe, code)
                if not result.get("success"):
                    raise ValueError(result.get("error") or "Code execution failed")
                summary = f"Executed code in {result.get('backend', 'unknown')} sandbox"
                return result, summary

            if task_type == "memory_consolidation":
                from services.agent.memory_agent import run_full_consolidation

                result = await run_full_consolidation(db, user_id)
                summary = (
                    f"Consolidated: deduped={result.get('deduped', 0)}, "
                    f"decayed={result.get('decayed', 0)}, "
                    f"categorized={result.get('categorized', 0)}"
                )
                return result, summary

            if task_type == "agent_subtask":
                # Generic agent subtask: runs a specified agent with a message
                agent_name = str(payload.get("agent_name", "teaching"))
                message = str(payload.get("message", ""))
                if not message.strip():
                    raise ValueError("agent_subtask requires a non-empty message")

                from services.agent.registry import get_agent, build_agent_context
                agent = get_agent(agent_name)
                if not agent:
                    raise ValueError(f"Unknown agent: {agent_name}")

                ctx = build_agent_context(
                    user_id=user_id,
                    course_id=_normalize_uuid(payload.get("course_id")),
                    message=message,
                    intent_type=payload.get("intent_type", "general"),
                )
                ctx = await agent.run(ctx, db)
                return {
                    "agent": agent_name,
                    "response": ctx.response or "",
                }, (ctx.response or "Agent subtask completed.")[:300]

            if task_type == "review_session":
                from services.agent.agenda_tasks import run_review_session

                result = await run_review_session(db, user_id, payload)
                return result, (result.get("summary", "") or "Review session completed.")[:300]

            if task_type == "reentry_session":
                from services.agent.agenda_tasks import run_reentry_session

                result = await run_reentry_session(db, user_id, payload)
                return result, (result.get("summary", "") or "Re-entry session prepared.")[:300]

            if task_type == "guided_session":
                raise ValueError("guided_session task type removed in Phase 2 consolidation")

            raise ValueError(f"Unsupported task_type: {task_type}")


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


async def _persist_plan_progress(
    db: AsyncSession,
    task_id: uuid.UUID,
    steps: list[JsonObject],
    *,
    results: list[TaskStepResult] | None = None,
    active_step_index: int | None = None,
) -> None:
    result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        return
    metadata = dict(task.metadata_json or {})
    metadata["plan_progress"] = _build_plan_progress(
        steps,
        results=results,
        active_step_index=active_step_index,
    )
    metadata["active_step_index"] = active_step_index
    task.metadata_json = metadata
    if results is not None:
        task.result_json = _build_plan_result_snapshot(
            steps,
            results,
            active_step_index=active_step_index,
        )
        task.step_results_json = results
        _refresh_task_checkpoint(task, active_step_index=active_step_index)
        task.provenance_json = merge_provenance(task.provenance_json, _merge_step_provenance(results))
    await db.commit()


async def _cancel_requested(db: AsyncSession, task_id: uuid.UUID) -> bool:
    task = await db.get(AgentTask, task_id, populate_existing=True)
    return bool(task and task.cancel_requested_at is not None)


async def _run_multi_step_plan(
    db: AsyncSession,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: JsonObject,
    db_factory,
) -> tuple[PlanResultPayload, str | None]:
    """Execute a multi-step plan created by TaskPlanner."""
    from services.agent.task_planner import execute_plan_step

    steps = payload.get("steps", [])
    course_id = _normalize_uuid(payload.get("course_id"))
    if not steps or not course_id:
        raise ValueError("multi_step requires 'steps' and 'course_id' in input_json")

    task_result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
    task = task_result.scalar_one_or_none()
    persisted_steps = (task.step_results_json if task else None) or ((task.result_json or {}) if task else {}).get("steps")
    results: list[TaskStepResult] = _coerce_step_results(persisted_steps)

    await _persist_plan_progress(db, task_id, steps, results=results, active_step_index=None)

    for step in steps:
        if any(result["step_index"] == step["step_index"] for result in results):
            continue
        if await _cancel_requested(db, task_id):
            raise TaskCancelledError(
                result_payload=_build_plan_result_payload(steps, results),
                summary=_build_plan_summary(steps, results),
            )
        await _persist_plan_progress(
            db,
            task_id,
            steps,
            results=results,
            active_step_index=step["step_index"],
        )
        # Check dependencies are met
        deps = step.get("depends_on", [])
        dep_ok = all(
            any(r["step_index"] == d and r.get("success") for r in results)
            for d in deps
        )
        if not dep_ok:
            results.append({
                "step_index": step["step_index"],
                "step_type": step.get("step_type", "unknown"),
                "title": step.get("title", f"Step {step['step_index'] + 1}"),
                "success": False,
                "input_message": step.get("description") or step.get("title", ""),
                "tool_calls": [],
                "output": "",
                "raw_output": "",
                "summary": "Skipped — dependency not met.",
                "error": "dependency_not_met",
                "verifier": None,
                "provenance": None,
            })
            await _persist_plan_progress(db, task_id, steps, results=results, active_step_index=None)
            continue

        step_result = await execute_plan_step(step, results, user_id, course_id, db, db_factory)
        results.append(step_result)
        await _persist_plan_progress(db, task_id, steps, results=results, active_step_index=None)
        if await _cancel_requested(db, task_id):
            raise TaskCancelledError(
                result_payload=_build_plan_result_payload(steps, results),
                summary=_build_plan_summary(steps, results),
            )

    payload = _build_plan_result_payload(steps, results)
    return payload, _build_plan_summary(steps, results)


async def drain_once() -> bool:
    """Claim and execute a single task.  Kept for backward compatibility."""
    ids = await _claim_pending_tasks(1)
    if not ids:
        return False
    await execute_task(ids[0])
    return True


async def _execute_with_semaphore(task_id: uuid.UUID) -> None:
    """Execute a single task while holding the worker semaphore."""
    assert _worker_semaphore is not None
    async with _worker_semaphore:
        await execute_task(task_id)


async def _wait_with_redis_or_stop(timeout: float) -> bool:
    """Wait for either a Redis task notification or a stop event.

    Returns *True* if a Redis notification was received (meaning new work is
    likely available), *False* if the stop event fired or the timeout expired.
    """
    assert _stop_event is not None

    async def _redis_wait() -> bool:
        result = await wait_for_task_notification(timeout=timeout)
        return result is not None

    async def _stop_wait() -> bool:
        await _stop_event.wait()
        return False

    done, pending = await asyncio.wait(
        [asyncio.create_task(_redis_wait()), asyncio.create_task(_stop_wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    # Cancel whichever coroutine lost the race.
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    # Return the result of the first completed coroutine.
    for task in done:
        try:
            return task.result()
        except Exception:
            return False
    return False


async def _run_loop() -> None:
    assert _stop_event is not None
    assert _worker_semaphore is not None
    max_concurrency = settings.activity_engine_max_concurrency
    use_redis = settings.activity_use_redis_notify

    current_idle_interval = IDLE_INTERVAL_SECONDS
    while not _stop_event.is_set():
        try:
            # Claim up to max_concurrency tasks in one batch.
            ids = await _claim_pending_tasks(max_concurrency)
        except Exception:
            logger.exception("Activity engine: failed to claim tasks")
            ids = []

        if ids:
            for task_id in ids:
                t = asyncio.create_task(_execute_with_semaphore(task_id))
                _inflight_tasks.add(t)
                t.add_done_callback(_inflight_tasks.discard)
            # Reset backoff when work is found
            current_idle_interval = IDLE_INTERVAL_SECONDS
            timeout = POLL_INTERVAL_SECONDS
        else:
            # Exponential backoff when idle to reduce unnecessary DB load
            timeout = current_idle_interval
            current_idle_interval = min(current_idle_interval * BACKOFF_MULTIPLIER, MAX_IDLE_INTERVAL_SECONDS)

        # When Redis notify is enabled, use pub/sub to wait for a wake-up
        # signal instead of sleeping for the full timeout.  If a notification
        # arrives we reset the backoff and immediately loop back to claim
        # tasks.  The existing stop_event is checked concurrently so that
        # shutdown requests are still honoured promptly.
        if use_redis and not ids:
            notified = await _wait_with_redis_or_stop(timeout)
            if notified:
                # A task was published -- reset backoff and claim immediately.
                current_idle_interval = IDLE_INTERVAL_SECONDS
            continue

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            continue


def start_activity_engine() -> None:
    global _worker_task, _stop_event, _worker_semaphore
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_semaphore = asyncio.Semaphore(settings.activity_engine_max_concurrency)
    _worker_task = asyncio.create_task(_run_loop())
    logger.info(
        "Activity engine started (max_concurrency=%d, redis_notify=%s)",
        settings.activity_engine_max_concurrency,
        settings.activity_use_redis_notify,
    )


async def stop_activity_engine() -> None:
    global _worker_task, _stop_event, _worker_semaphore
    if not _worker_task:
        return
    if _stop_event is not None:
        _stop_event.set()
    try:
        # Wait for the polling loop to exit.
        await _worker_task
    finally:
        _worker_task = None
        _stop_event = None
    # Drain any in-flight concurrent tasks that were already dispatched.
    if _inflight_tasks:
        logger.info("Waiting for %d in-flight task(s) to finish…", len(_inflight_tasks))
        await asyncio.gather(*_inflight_tasks, return_exceptions=True)
    _inflight_tasks.clear()
    _worker_semaphore = None
    # Close the shared Redis connection used for task notifications.
    await _close_redis_notify()
    logger.info("Activity engine stopped")
