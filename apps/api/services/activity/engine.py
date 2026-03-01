"""Background execution engine for durable agent tasks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select

from database import async_session
from models.agent_task import AgentTask
from services.activity.tasks import APPROVAL_REQUIRED_STATUS, EXECUTABLE_TASK_STATUSES, _truncate_summary

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1.0
IDLE_INTERVAL_SECONDS = 2.0

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


async def submit_task(
    *,
    user_id: uuid.UUID,
    task_type: str,
    title: str,
    course_id: uuid.UUID | None = None,
    summary: str | None = None,
    source: str = "workflow",
    input_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
    requires_approval: bool = False,
    max_attempts: int = 2,
) -> AgentTask:
    from services.activity.tasks import create_task

    async with async_session() as db:
        task = await create_task(
            db,
            user_id=user_id,
            course_id=course_id,
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
        await db.commit()
        await db.refresh(task)
        return task


async def approve_task(task_id: uuid.UUID, user_id: uuid.UUID) -> AgentTask | None:
    async with async_session() as db:
        result = await db.execute(
            select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            return None
        if task.status != APPROVAL_REQUIRED_STATUS:
            return task
        task.approved_at = _utcnow()
        task.status = "queued"
        task.error_message = None
        task.completed_at = None
        await db.commit()
        await db.refresh(task)
        return task


async def cancel_task(task_id: uuid.UUID, user_id: uuid.UUID) -> AgentTask | None:
    async with async_session() as db:
        result = await db.execute(
            select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            return None
        now = _utcnow()
        task.cancel_requested_at = now
        if task.status in {"queued", "retrying", APPROVAL_REQUIRED_STATUS}:
            task.status = "cancelled"
            task.completed_at = now
        await db.commit()
        await db.refresh(task)
        return task


async def retry_task(task_id: uuid.UUID, user_id: uuid.UUID) -> AgentTask | None:
    async with async_session() as db:
        result = await db.execute(
            select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            return None
        if task.status == "running":
            return task
        task.error_message = None
        task.result_json = None
        task.summary = None
        task.started_at = None
        task.completed_at = None
        task.cancel_requested_at = None
        task.status = _queueable_status(task)
        await db.commit()
        await db.refresh(task)
        return task


async def _claim_next_task() -> uuid.UUID | None:
    async with async_session() as db:
        result = await db.execute(
            select(AgentTask)
            .where(
                AgentTask.status.in_(tuple(EXECUTABLE_TASK_STATUSES)),
                or_(AgentTask.requires_approval.is_(False), AgentTask.approved_at.is_not(None)),
                AgentTask.cancel_requested_at.is_(None),
            )
            .order_by(AgentTask.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        task = result.scalar_one_or_none()
        if not task:
            return None
        task.status = "running"
        task.started_at = _utcnow()
        task.attempts += 1
        await db.commit()
        return task.id


async def execute_task(task_id: uuid.UUID) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        payload = task.input_json or {}

    try:
        result_payload, summary = await _dispatch_task(task_type=task.task_type, user_id=task.user_id, payload=payload)
    except Exception as exc:
        logger.exception("Agent task failed: %s (%s)", task_id, exc)
        return await _mark_task_failure(task_id, str(exc))

    return await _mark_task_success(task_id, result_payload=result_payload, summary=summary)


async def _mark_task_success(task_id: uuid.UUID, *, result_payload: dict[str, Any], summary: str | None) -> bool:
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
            await db.commit()
            return False
        task.status = "completed"
        task.summary = _truncate_summary(summary)
        task.result_json = result_payload
        task.error_message = None
        task.completed_at = now
        await db.commit()
        return True


async def _mark_task_failure(task_id: uuid.UUID, error_message: str) -> bool:
    async with async_session() as db:
        result = await db.execute(select(AgentTask).where(AgentTask.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            return False
        now = _utcnow()
        task.error_message = error_message
        task.completed_at = None
        if task.cancel_requested_at is not None:
            task.status = "cancelled"
            task.completed_at = now
        elif task.attempts < max(task.max_attempts, 1):
            task.status = "retrying"
        else:
            task.status = "failed"
            task.completed_at = now
        await db.commit()
        return True


async def _dispatch_task(*, task_type: str, user_id: uuid.UUID, payload: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    async with async_session() as db:
        if task_type == "weekly_prep":
            from services.workflow.weekly_prep import run_weekly_prep

            result = await run_weekly_prep(db, user_id)
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

        if task_type == "multi_step":
            return await _run_multi_step_plan(db, user_id, payload)

        raise ValueError(f"Unsupported task_type: {task_type}")


async def _run_multi_step_plan(
    db: AsyncSession, user_id: uuid.UUID, payload: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Execute a multi-step plan created by TaskPlanner."""
    from services.agent.task_planner import execute_plan_step

    steps = payload.get("steps", [])
    course_id = _normalize_uuid(payload.get("course_id"))
    if not steps or not course_id:
        raise ValueError("multi_step requires 'steps' and 'course_id' in input_json")

    results: list[dict] = []
    completed = 0
    failed = 0

    for step in steps:
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
                "success": False,
                "output": "",
                "summary": "Skipped — dependency not met.",
            })
            failed += 1
            continue

        step_result = await execute_plan_step(step, results, user_id, course_id, db)
        results.append(step_result)
        if step_result.get("success"):
            completed += 1
        else:
            failed += 1

    summary_parts = [f"{completed}/{len(steps)} steps completed"]
    if failed:
        summary_parts.append(f"{failed} failed")
    return {
        "steps": results,
        "completed": completed,
        "failed": failed,
        "total": len(steps),
    }, "; ".join(summary_parts)


async def drain_once() -> bool:
    task_id = await _claim_next_task()
    if not task_id:
        return False
    await execute_task(task_id)
    return True


async def _run_loop() -> None:
    assert _stop_event is not None
    while not _stop_event.is_set():
        try:
            processed = await drain_once()
        except Exception:
            logger.exception("Agent task engine loop failed")
            processed = False
        timeout = POLL_INTERVAL_SECONDS if processed else IDLE_INTERVAL_SECONDS
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            continue


def start_activity_engine() -> None:
    global _worker_task, _stop_event
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_run_loop())
    logger.info("Activity engine started")


async def stop_activity_engine() -> None:
    global _worker_task, _stop_event
    if not _worker_task:
        return
    if _stop_event is not None:
        _stop_event.set()
    try:
        await _worker_task
    finally:
        _worker_task = None
        _stop_event = None
        logger.info("Activity engine stopped")
