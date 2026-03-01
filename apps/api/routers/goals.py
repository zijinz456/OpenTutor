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
from models.ingestion import Assignment
from models.study_goal import StudyGoal
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.spaced_repetition.forgetting_forecast import predict_forgetting
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


def _days_until(value: datetime | None) -> int | None:
    if value is None:
        return None
    now = datetime.now(timezone.utc)
    target = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return max(int((target - now).total_seconds() // 86400), 0)


@router.get("/{course_id}/next-action", response_model=NextActionResponse)
async def get_next_action(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, course_id, user_id=user.id)

    active_goal_result = await db.execute(
        select(StudyGoal)
        .where(
            StudyGoal.user_id == user.id,
            StudyGoal.course_id == course_id,
            StudyGoal.status == "active",
        )
        .order_by(StudyGoal.updated_at.desc(), StudyGoal.created_at.desc())
        .limit(1)
    )
    active_goal = active_goal_result.scalar_one_or_none()
    if active_goal:
        days_until_target = _days_until(active_goal.target_date)
        if active_goal.next_action:
            return NextActionResponse(
                course_id=str(course_id),
                goal_id=str(active_goal.id),
                title=f"Continue: {active_goal.title}",
                reason="An active goal already has a concrete next action, so the safest move is to keep the agent aligned with it.",
                source="manual",
                recommended_action=active_goal.next_action,
                suggested_task_type="multi_step",
            )
        if days_until_target is not None and days_until_target <= 7:
            return NextActionResponse(
                course_id=str(course_id),
                goal_id=str(active_goal.id),
                title=f"Protect deadline: {active_goal.title}",
                reason=f"This active goal has a target date in {days_until_target} day(s), so it should take priority now.",
                source="deadline",
                recommended_action=f"Break {active_goal.title} into a concrete plan for the next 7 days.",
                suggested_task_type="exam_prep",
            )
        return NextActionResponse(
            course_id=str(course_id),
            goal_id=str(active_goal.id),
            title=f"Advance: {active_goal.title}",
            reason="There is an active goal but no explicit next action, so the system should convert it into the next executable step.",
            source="recent_goal",
            recommended_action=f"Turn {active_goal.title} into a concrete study task with one measurable deliverable.",
            suggested_task_type="multi_step",
        )

    assignment_result = await db.execute(
        select(Assignment)
        .where(
            Assignment.course_id == course_id,
            Assignment.status == "active",
            Assignment.due_date.is_not(None),
        )
        .order_by(Assignment.due_date.asc())
        .limit(1)
    )
    next_assignment = assignment_result.scalar_one_or_none()
    if next_assignment and next_assignment.due_date:
        days_until_due = _days_until(next_assignment.due_date) or 0
        if days_until_due <= 7:
            return NextActionResponse(
                course_id=str(course_id),
                goal_id=None,
                title=f"Upcoming deadline: {next_assignment.title}",
                reason=f"This assignment is due in {days_until_due} day(s), so short-horizon planning should happen before deeper exploration.",
                source="deadline",
                recommended_action=f"Review the requirements for {next_assignment.title} and produce a task plan for the remaining time.",
                suggested_task_type="assignment_analysis",
            )

    failed_task_result = await db.execute(
        select(AgentTask)
        .where(
            AgentTask.user_id == user.id,
            AgentTask.course_id == course_id,
            AgentTask.status.in_(("failed", "cancelled", "rejected")),
        )
        .order_by(AgentTask.updated_at.desc(), AgentTask.created_at.desc())
        .limit(1)
    )
    failed_task = failed_task_result.scalar_one_or_none()
    if failed_task:
        recommended_action = (
            f"Retry {failed_task.title} after checking why it {failed_task.status.replace('_', ' ')}."
            if failed_task.status != "cancelled"
            else f"Resume {failed_task.title} from its last checkpoint."
        )
        return NextActionResponse(
            course_id=str(course_id),
            goal_id=str(failed_task.goal_id) if failed_task.goal_id else None,
            title=f"Recover task: {failed_task.title}",
            reason="The most recent durable task did not finish cleanly, so recovery is more valuable than starting unrelated work.",
            source="task_failure",
            recommended_action=recommended_action,
            suggested_task_type=failed_task.task_type,
        )

    forecast = await predict_forgetting(db, user.id, course_id)
    risky_items = [
        item for item in forecast.get("predictions", [])
        if item.get("urgency") in {"overdue", "urgent", "warning"}
    ]
    if risky_items:
        top_item = risky_items[0]
        return NextActionResponse(
            course_id=str(course_id),
            goal_id=None,
            title=f"Refresh memory: {top_item.get('title') or 'course material'}",
            reason="The forgetting forecast shows material that is close to slipping below the retention threshold.",
            source="forgetting_risk",
            recommended_action=f"Review {top_item.get('title') or 'the at-risk material'} before its retrievability drops further.",
            suggested_task_type="wrong_answer_review",
        )

    return NextActionResponse(
        course_id=str(course_id),
        goal_id=None,
        title="Set the next goal",
        reason="No active goal, deadline, failed task, or forgetting risk is currently dominating the queue.",
        source="manual",
        recommended_action="Create a concrete study goal or ask the agent to generate a prioritized study plan.",
        suggested_task_type="multi_step",
    )


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
    linked_task_count = int(count_result.scalar_one() or 0)
    return StudyGoalResponse(**serialize_model(goal, extra={"linked_task_count": linked_task_count}))
