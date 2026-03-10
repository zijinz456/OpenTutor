"""Agenda service — the agent's decision-making loop.

Central entry point for:
- ``run_agenda_tick()``   — called by scheduler and manual API
- ``resolve_next_action()`` — called by goals router (replaces the old inline resolver)
- ``queue_decision()``    — materialises a decision into an AgentTask

The service is *stateless per call*; all durable state lives in
AgendaRun (audit), AgentTask (execution), and StudyGoal (objectives).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agenda_run import AgendaRun
from models.agent_task import AgentTask
from services.activity.engine import resume_task, retry_task, submit_task
from services.agent.agenda_ranking import AgendaDecision, rank_signals
from services.agent.agenda_signals import AgendaSignal, collect_signals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dedup / cooldown constants
# ---------------------------------------------------------------------------

# Same dedup_key must not materialise more than once in this window.
DEDUP_WINDOW_HOURS = 24

# Minimum gap between proactive notifications for the same course.
NOTIFICATION_COOLDOWN_HOURS = 6


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_agenda_tick(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    trigger: str = "scheduler",
    *,
    db: AsyncSession,
    notify: bool = True,
) -> AgendaRun:
    """Execute one tick of the agenda loop for a user[+course].

    1. Collect signals
    2. Rank and pick the best action
    3. Check dedup / cooldown
    4. Materialise as AgentTask (or noop)
    5. Persist an AgendaRun record
    6. Optionally push a notification
    """
    run = AgendaRun(
        user_id=user_id,
        course_id=course_id,
        trigger=trigger,
        status="noop",
    )

    def _noop(reason: str | None = None) -> None:
        """Mark run as noop with an optional skip reason."""
        run.status = "noop"
        if reason:
            run.decision_json = {**(run.decision_json or {}), "skipped_reason": reason}

    try:
        signals = await collect_signals(user_id, course_id, db=db)
        run.signals_json = _serialise_signals(signals)

        decision = rank_signals(signals)
        run.decision_json = decision.to_dict()
        run.top_signal_type = decision.signal.signal_type if decision.signal else None
        run.dedup_key = decision.dedup_key

        if decision.action == "noop":
            _noop()
        elif decision.dedup_key and await _is_deduped(db, user_id, decision.dedup_key):
            _noop("dedup")
        elif (
            decision.action == "submit"
            and decision.task_type
            and await _has_active_task(db, user_id, course_id, decision.task_type)
        ):
            _noop("active_task_exists")
        else:
            # --- Materialise ---
            task = await queue_decision(decision, user_id=user_id, course_id=course_id, db=db)
            if task:
                run.task_id = task.id
                run.goal_id = decision.goal_id
                run.status = {
                    "submit": "queued_task",
                    "resume": "resumed_task",
                    "retry": "retried_task",
                }.get(decision.action, "queued_task")
            else:
                run.status = "failed"
                run.error_message = "queue_decision returned None"

            # --- Notify (removed in Phase 1.1 refactor) ---
            if notify and task and decision.action == "submit":
                logger.debug("Notification skipped (removed): %s", decision.task_title)

    except Exception as exc:
        logger.exception("Agenda tick failed for user=%s course=%s", user_id, course_id)
        run.status = "failed"
        run.error_message = str(exc)[:500]

    run.completed_at = datetime.now(timezone.utc)
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run


async def resolve_next_action(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    db: AsyncSession,
) -> AgendaDecision:
    """Resolve the best next action for a specific course (used by goals router).

    This replaces the old ``_resolve_next_action_decision()`` in goals.py
    so that the same logic is shared between the API and the scheduler.
    """
    signals = await collect_signals(user_id, course_id, db=db)
    decision = rank_signals(signals)

    # Fallback: if no signal found, suggest creating a goal
    if decision.action == "noop":
        decision.action = "submit"
        decision.task_type = "multi_step"
        decision.task_title = "Generate prioritized study plan"
        decision.task_summary = "Create a concrete study goal or ask the agent to generate a prioritized study plan."
        decision.plan_prompt = decision.task_summary
        decision.reason = "No active goal, deadline, failed task, or forgetting risk dominates the queue."

    return decision


async def queue_decision(
    decision: AgendaDecision,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    db: AsyncSession,
) -> AgentTask | None:
    """Materialise a ranked decision into an AgentTask.

    Handles submit / resume / retry dispatch.
    """
    if decision.action in ("resume", "retry") and decision.existing_task_id:
        if decision.action == "resume":
            return await resume_task(decision.existing_task_id, user_id, db=db)
        return await retry_task(decision.existing_task_id, user_id, db=db)

    if decision.action == "submit":
        input_json = dict(decision.input_json or {})

        # For multi_step tasks, generate a plan via the task planner.
        # create_plan requires a non-None course_id; skip if unavailable.
        if decision.task_type == "multi_step" and decision.plan_prompt and course_id:
            try:
                from services.agent.task_planner import create_plan
                steps = await create_plan(decision.plan_prompt, user_id, course_id)
                input_json.update({
                    "course_id": str(course_id),
                    "steps": steps,
                    "plan_prompt": decision.plan_prompt,
                })
            except (ConnectionError, TimeoutError, ValueError, RuntimeError):
                logger.exception("Plan creation failed, submitting without steps")
                input_json["course_id"] = str(course_id)
        elif course_id:
            input_json.setdefault("course_id", str(course_id))

        task = await submit_task(
            user_id=user_id,
            db=db,
            course_id=course_id,
            goal_id=decision.goal_id,
            task_type=decision.task_type or "multi_step",
            title=decision.task_title or "Agent task",
            summary=decision.task_summary or decision.reason,
            source="agenda",
            input_json=input_json,
            metadata_json={
                "agenda_decision": decision.to_dict(),
            },
            requires_approval=decision.task_type in ("reentry_session",),
            max_attempts=2,
        )
        return task

    return None


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------

async def _is_deduped(db: AsyncSession, user_id: uuid.UUID, dedup_key: str) -> bool:
    """Check if the same dedup_key was already used within DEDUP_WINDOW_HOURS."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUP_WINDOW_HOURS)
    result = await db.execute(
        select(AgendaRun.id)
        .where(
            AgendaRun.user_id == user_id,
            AgendaRun.dedup_key == dedup_key,
            AgendaRun.created_at >= cutoff,
            AgendaRun.status.notin_(("noop", "failed")),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _has_active_task(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    task_type: str,
) -> bool:
    """Check if there's already a queued/running/pending_approval task of this type."""
    query = (
        select(AgentTask.id)
        .where(
            AgentTask.user_id == user_id,
            AgentTask.task_type == task_type,
            AgentTask.status.in_(("queued", "running", "pending_approval")),
        )
    )
    if course_id:
        query = query.where(AgentTask.course_id == course_id)
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def _notification_on_cooldown(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
) -> bool:
    """Check if a proactive notification was sent recently for this course."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NOTIFICATION_COOLDOWN_HOURS)
    query = (
        select(AgendaRun.id)
        .where(
            AgendaRun.user_id == user_id,
            AgendaRun.status.in_(("queued_task", "notified")),
            AgendaRun.created_at >= cutoff,
        )
    )
    if course_id:
        query = query.where(AgendaRun.course_id == course_id)
    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialise_signals(signals: list[AgendaSignal]) -> list[dict]:
    return [
        {
            "signal_type": s.signal_type,
            "course_id": str(s.course_id) if s.course_id else None,
            "entity_id": s.entity_id,
            "title": s.title,
            "urgency": s.urgency,
        }
        for s in signals
    ]
