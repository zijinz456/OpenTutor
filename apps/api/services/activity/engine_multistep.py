"""Multi-step plan execution, goal sync, and auto-repair follow-ups."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import utcnow as _utcnow
from models.agent_task import AgentTask
from models.study_goal import StudyGoal
from services.activity.task_records import create_task
from services.activity.task_types import JsonObject, PlanResultPayload, TaskStepResult
from services.provenance import merge_provenance
from services.activity.engine_helpers import (
    TaskCancelledError,
    _build_plan_progress,
    _build_plan_result_payload,
    _build_plan_result_snapshot,
    _build_plan_summary,
    _coerce_step_results,
    _extract_first_action,
    _merge_step_provenance,
    _normalize_uuid,
    _refresh_task_checkpoint,
    _serialize_goal_update,
)
from services.activity.engine_lifecycle import _record_task_audit

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Goal sync
# ------------------------------------------------------------------

async def _sync_goal_after_task_success(
    db: AsyncSession,
    task: AgentTask,
    result_payload: JsonObject,
) -> dict[str, Any] | None:
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


# ------------------------------------------------------------------
# Auto-repair follow-up
# ------------------------------------------------------------------

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
        except (ConnectionError, TimeoutError, ValueError, RuntimeError, OSError) as exc:
            logger.warning("Auto repair follow-up planning failed for task %s: %s", task.id, exc)
            return None
        except Exception as exc:  # noqa: BLE001 — LLM API errors (openai.APIError, httpx.*) aren't stdlib
            logger.warning("Auto repair planning failed (API error) for task %s: %s", task.id, exc)
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


# ------------------------------------------------------------------
# Multi-step plan helpers
# ------------------------------------------------------------------

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
        if any(r["step_index"] == step["step_index"] for r in results):
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
                "summary": "Skipped \u2014 dependency not met.",
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

    final_payload = _build_plan_result_payload(steps, results)
    return final_payload, _build_plan_summary(steps, results)
