"""Task review payload builders — post-completion review and follow-up generation.

Extracted from tasks.py. Builds structured review payloads for completed tasks
including outcome summaries, blockers, follow-up suggestions, and goal updates.
"""

from __future__ import annotations

from typing import Any

from models.agent_task import AgentTask
from services.activity.task_types import (
    GoalUpdatePayload,
    JsonObject,
    TaskFollowUpPayload,
    TaskReviewPayload,
    TaskStepResult,
    _truncate_summary,
    normalize_task_status,
)


def _extract_first_action(text: Any) -> str | None:
    """Extract the first actionable line from a text block."""
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
    """Build a structured review payload for a completed task."""
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
    """Attach a review payload to the task's result JSON."""
    payload = dict(result_payload or {})
    payload["task_review"] = review_payload
    return payload
