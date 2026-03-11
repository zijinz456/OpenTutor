"""Agenda endpoints — observe and trigger the agent's decision loop."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.agenda_run import AgendaRun
from models.agent_task import AgentTask
from models.study_goal import StudyGoal
from models.user import User
from services.agent.agenda import resolve_next_action, run_agenda_tick
from services.auth.dependency import get_current_user
from utils.serializers import serialize_model

router = APIRouter()


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class AgendaRunResponse(BaseModel):
    id: str
    user_id: str
    course_id: str | None
    goal_id: str | None
    trigger: str
    status: str
    top_signal_type: str | None
    signals_json: list | dict | None
    decision_json: dict | None
    task_id: str | None
    dedup_key: str | None
    error_message: str | None
    created_at: str | None
    completed_at: str | None


class AgendaTickRequest(BaseModel):
    course_id: uuid.UUID | None = None
    trigger: str = "manual"


class AgendaTickResponse(BaseModel):
    run_id: str
    status: str
    task_id: str | None
    top_signal_type: str | None
    decision_json: dict | None


class AgendaDecisionLogRequest(BaseModel):
    course_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    trigger: str = "user_action"
    status: str = "noop"
    top_signal_type: str | None = "manual_override"
    action: str
    title: str | None = None
    reason: str | None = None
    decision_type: str | None = None
    source: str | None = None
    metadata_json: dict | None = None
    dedup_key: str | None = None


class CourseAgendaResponse(BaseModel):
    course_id: str
    active_goal: dict | None
    next_action: dict | None
    queued_tasks: int
    running_tasks: int
    blocked_tasks: int
    latest_run: dict | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/tick", response_model=AgendaTickResponse)
async def trigger_tick(
    body: AgendaTickRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger one agenda tick for the current user."""
    run = await run_agenda_tick(
        user_id=user.id,
        course_id=body.course_id,
        trigger=body.trigger or "manual",
        db=db,
        notify=True,
    )
    return AgendaTickResponse(
        run_id=str(run.id),
        status=run.status,
        task_id=str(run.task_id) if run.task_id else None,
        top_signal_type=run.top_signal_type,
        decision_json=run.decision_json,
    )


@router.post("/log-decision", response_model=AgendaRunResponse)
async def log_decision(
    body: AgendaDecisionLogRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Append a user decision entry to agenda history for timeline visibility."""
    decision_json: dict = {
        "action": body.action,
        "reason": body.reason,
        "decision_type": body.decision_type,
        "source": body.source,
    }
    if body.title:
        decision_json["task_title"] = body.title
    if body.metadata_json:
        decision_json["metadata"] = body.metadata_json

    run = AgendaRun(
        user_id=user.id,
        course_id=body.course_id,
        goal_id=body.goal_id,
        trigger=body.trigger or "user_action",
        status=body.status or "noop",
        top_signal_type=body.top_signal_type,
        decision_json=decision_json,
        signals_json=[{"signal_type": body.top_signal_type}] if body.top_signal_type else [],
        dedup_key=body.dedup_key,
        completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return AgendaRunResponse(**serialize_model(run))


@router.get("/runs", response_model=list[AgendaRunResponse])
async def list_runs(
    course_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent agenda decision history."""
    query = select(AgendaRun).where(AgendaRun.user_id == user.id)
    if course_id:
        query = query.where(AgendaRun.course_id == course_id)
    query = query.order_by(AgendaRun.created_at.desc()).limit(limit)
    result = await db.execute(query)
    runs = result.scalars().all()
    return [AgendaRunResponse(**serialize_model(r)) for r in runs]


@router.get("/courses/{course_id}", response_model=CourseAgendaResponse)
async def get_course_agenda(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current agenda state for a course: goal, next action, tasks, latest run."""

    # Active goal
    goal_result = await db.execute(
        select(StudyGoal)
        .where(
            StudyGoal.user_id == user.id,
            StudyGoal.course_id == course_id,
            StudyGoal.status == "active",
        )
        .order_by(StudyGoal.updated_at.desc())
        .limit(1)
    )
    goal = goal_result.scalar_one_or_none()

    # Next action decision (computed live)
    decision = await resolve_next_action(user.id, course_id, db)

    # Task counts
    async def _count_tasks(status_list: list[str]) -> int:
        r = await db.execute(
            select(func.count(AgentTask.id)).where(
                AgentTask.user_id == user.id,
                AgentTask.course_id == course_id,
                AgentTask.status.in_(status_list),
            )
        )
        return int(r.scalar() or 0)

    queued = await _count_tasks(["queued"])
    running = await _count_tasks(["running"])
    blocked = await _count_tasks(["pending_approval", "failed", "cancelled"])

    # Latest agenda run
    run_result = await db.execute(
        select(AgendaRun)
        .where(AgendaRun.user_id == user.id, AgendaRun.course_id == course_id)
        .order_by(AgendaRun.created_at.desc())
        .limit(1)
    )
    latest_run = run_result.scalar_one_or_none()

    return CourseAgendaResponse(
        course_id=str(course_id),
        active_goal=serialize_model(goal) if goal else None,
        next_action=decision.to_dict() if decision else None,
        queued_tasks=queued,
        running_tasks=running,
        blocked_tasks=blocked,
        latest_run=serialize_model(latest_run) if latest_run else None,
    )
