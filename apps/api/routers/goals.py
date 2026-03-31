"""Durable study-goal endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from libs.exceptions import NotFoundError
from models.agent_task import AgentTask
from models.study_goal import StudyGoal
from models.user import User
from schemas.task import AgentTaskResponse
from services.activity.task_records import serialize_task
from services.agent.agenda import queue_decision, resolve_next_action
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from utils.serializers import serialize_model

router = APIRouter()


class StudyGoalResponse(BaseModel):
    id: str
    user_id: str
    course_id: str | None
    title: str
    objective: str
    success_metric: str | None
    current_milestone: str | None
    next_action: str | None
    status: str
    confidence: str | None
    target_date: str | None
    metadata_json: dict | None
    linked_task_count: int
    created_at: str | None
    updated_at: str | None
    completed_at: str | None


class CreateGoalRequest(BaseModel):
    title: str
    objective: str
    course_id: uuid.UUID | None = None
    success_metric: str | None = None
    current_milestone: str | None = None
    next_action: str | None = None
    status: str = "active"
    confidence: str | None = None
    target_date: datetime | None = None
    metadata_json: dict | None = None


class UpdateGoalRequest(BaseModel):
    title: str | None = None
    objective: str | None = None
    success_metric: str | None = None
    current_milestone: str | None = None
    next_action: str | None = None
    status: str | None = None
    confidence: str | None = None
    target_date: datetime | None = None
    metadata_json: dict | None = None


class NextActionResponse(BaseModel):
    course_id: str
    goal_id: str | None
    title: str
    reason: str
    source: str
    recommended_action: str
    suggested_task_type: str | None
    queue_label: str | None = None
    queue_ready: bool = True


def _decision_to_next_action_response(
    decision,
    course_id: uuid.UUID,
) -> NextActionResponse:
    """Convert an AgendaDecision to the legacy NextActionResponse shape."""
    source_map = {
        "active_goal": "recent_goal",
        "deadline": "deadline",
        "failed_task": "task_failure",
        "forgetting_risk": "forgetting_risk",
        "weak_area": "forgetting_risk",
        "inactivity": "manual",
    }
    signal_type = decision.signal.signal_type if decision.signal else "manual"
    queue_label_map = {
        "submit": "Queue task",
        "resume": "Resume task",
        "retry": "Retry task",
        "noop": None,
    }
    return NextActionResponse(
        course_id=str(course_id),
        goal_id=str(decision.goal_id) if decision.goal_id else None,
        title=decision.task_title or "Set the next goal",
        reason=decision.reason,
        source=source_map.get(signal_type, "manual"),
        recommended_action=decision.task_summary or decision.reason,
        suggested_task_type=decision.task_type,
        queue_label=queue_label_map.get(decision.action, "Queue task"),
    )


@router.get("/{course_id}/next-action", response_model=NextActionResponse)
async def get_next_action(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, course_id, user_id=user.id)
    decision = await resolve_next_action(user.id, course_id, db)
    return _decision_to_next_action_response(decision, course_id)


@router.post("/{course_id}/next-action/queue", response_model=AgentTaskResponse)
async def queue_next_action(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, course_id, user_id=user.id)
    decision = await resolve_next_action(user.id, course_id, db)
    task = await queue_decision(decision, user_id=user.id, course_id=course_id, db=db)

    if not task:
        raise NotFoundError("Task", decision.existing_task_id or "next_action")

    return AgentTaskResponse(**serialize_task(task))


@router.get("/", response_model=list[StudyGoalResponse])
async def list_goals(
    course_id: uuid.UUID | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(StudyGoal).where(StudyGoal.user_id == user.id)
    if course_id:
        query = query.where(StudyGoal.course_id == course_id)
    if status:
        query = query.where(StudyGoal.status == status)
    query = query.order_by(StudyGoal.created_at.desc()).limit(limit)
    result = await db.execute(query)
    goals = result.scalars().all()
    if not goals:
        return []

    goal_ids = [goal.id for goal in goals]
    count_result = await db.execute(
        select(AgentTask.goal_id, func.count(AgentTask.id))
        .where(AgentTask.goal_id.in_(goal_ids))
        .group_by(AgentTask.goal_id)
    )
    counts = {row[0]: row[1] for row in count_result.all()}
    return [
        StudyGoalResponse(**serialize_model(goal, extra={"linked_task_count": int(counts.get(goal.id, 0))}))
        for goal in goals
    ]


@router.post("/", response_model=StudyGoalResponse, status_code=201)
async def create_goal(
    body: CreateGoalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.course_id:
        await get_course_or_404(db, body.course_id, user_id=user.id)
    goal = StudyGoal(
        user_id=user.id,
        course_id=body.course_id,
        title=body.title.strip(),
        objective=body.objective.strip(),
        success_metric=(body.success_metric or None),
        current_milestone=(body.current_milestone or None),
        next_action=(body.next_action or None),
        status=body.status or "active",
        confidence=body.confidence,
        target_date=body.target_date,
        metadata_json=body.metadata_json,
        completed_at=datetime.now(timezone.utc) if body.status == "completed" else None,
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return StudyGoalResponse(**serialize_model(goal, extra={"linked_task_count": 0}))


@router.patch("/{goal_id}", response_model=StudyGoalResponse)
async def update_goal(
    goal_id: uuid.UUID,
    body: UpdateGoalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(StudyGoal).where(StudyGoal.id == goal_id, StudyGoal.user_id == user.id))
    goal = result.scalar_one_or_none()
    if not goal:
        raise NotFoundError("Goal", goal_id)

    payload = body.model_dump(exclude_unset=True)
    if "title" in payload and payload["title"] is not None:
        goal.title = payload["title"].strip()
    if "objective" in payload and payload["objective"] is not None:
        goal.objective = payload["objective"].strip()
    for field in ("success_metric", "current_milestone", "next_action", "confidence", "target_date", "metadata_json"):
        if field in payload:
            setattr(goal, field, payload[field])
    if "status" in payload and payload["status"] is not None:
        goal.status = payload["status"]
        goal.completed_at = datetime.now(timezone.utc) if payload["status"] == "completed" else None

    await db.commit()
    await db.refresh(goal)

    count_result = await db.execute(select(func.count(AgentTask.id)).where(AgentTask.goal_id == goal.id))
    linked_task_count = int(count_result.scalar() or 0)
    return StudyGoalResponse(**serialize_model(goal, extra={"linked_task_count": linked_task_count}))
