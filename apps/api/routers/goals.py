"""Durable study-goal endpoints."""

import uuid
from dataclasses import dataclass
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
from routers.tasks import AgentTaskResponse
from services.activity.engine import resume_task, retry_task, submit_task
from services.activity.tasks import serialize_task
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
    queue_label: str | None = None
    queue_ready: bool = True


@dataclass
class NextActionDecision:
    response: NextActionResponse
    queue_mode: str
    task_type: str | None = None
    task_title: str | None = None
    task_summary: str | None = None
    input_json: dict | None = None
    goal_id: uuid.UUID | None = None
    existing_task_id: uuid.UUID | None = None
    plan_prompt: str | None = None


def _days_until(value: datetime | None) -> int | None:
    if value is None:
        return None
    now = datetime.now(timezone.utc)
    target = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return max(int((target - now).total_seconds() // 86400), 0)


async def _resolve_next_action_decision(
    *,
    course_id: uuid.UUID,
    user: User,
    db: AsyncSession,
) -> NextActionDecision:
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
            objective = getattr(active_goal, "objective", None) or active_goal.title
            action_prompt = (
                f"Goal: {active_goal.title}\n"
                f"Objective: {objective}\n"
                f"Immediate next action: {active_goal.next_action}"
            )
            return NextActionDecision(
                response=NextActionResponse(
                    course_id=str(course_id),
                    goal_id=str(active_goal.id),
                    title=f"Continue: {active_goal.title}",
                    reason="An active goal already has a concrete next action, so the safest move is to keep the agent aligned with it.",
                    source="manual",
                    recommended_action=active_goal.next_action,
                    suggested_task_type="multi_step",
                    queue_label="Queue next step",
                ),
                queue_mode="submit",
                task_type="multi_step",
                task_title=f"Execute next step: {active_goal.title}",
                task_summary=active_goal.next_action,
                goal_id=active_goal.id,
                plan_prompt=action_prompt,
            )
        if days_until_target is not None and days_until_target <= 7:
            recommended_action = f"Break {active_goal.title} into a concrete plan for the next 7 days."
            return NextActionDecision(
                response=NextActionResponse(
                    course_id=str(course_id),
                    goal_id=str(active_goal.id),
                    title=f"Protect deadline: {active_goal.title}",
                    reason=f"This active goal has a target date in {days_until_target} day(s), so it should take priority now.",
                    source="deadline",
                    recommended_action=recommended_action,
                    suggested_task_type="exam_prep",
                    queue_label="Queue exam prep",
                ),
                queue_mode="submit",
                task_type="exam_prep",
                task_title=f"Exam prep: {active_goal.title}",
                task_summary=recommended_action,
                goal_id=active_goal.id,
                input_json={
                    "course_id": str(course_id),
                    "exam_topic": active_goal.title,
                    "days_until_exam": max(days_until_target, 1),
                },
            )
        recommended_action = f"Turn {active_goal.title} into a concrete study task with one measurable deliverable."
        objective = getattr(active_goal, "objective", None) or active_goal.title
        return NextActionDecision(
            response=NextActionResponse(
                course_id=str(course_id),
                goal_id=str(active_goal.id),
                title=f"Advance: {active_goal.title}",
                reason="There is an active goal but no explicit next action, so the system should convert it into the next executable step.",
                source="recent_goal",
                recommended_action=recommended_action,
                suggested_task_type="multi_step",
                queue_label="Queue study plan",
            ),
            queue_mode="submit",
            task_type="multi_step",
            task_title=f"Plan next step: {active_goal.title}",
            task_summary=recommended_action,
            goal_id=active_goal.id,
            plan_prompt=(
                f"Goal: {active_goal.title}\n"
                f"Objective: {objective}\n"
                f"Requested planning outcome: {recommended_action}"
            ),
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
            recommended_action = (
                f"Review the requirements for {next_assignment.title} and produce a task plan for the remaining time."
            )
            return NextActionDecision(
                response=NextActionResponse(
                    course_id=str(course_id),
                    goal_id=None,
                    title=f"Upcoming deadline: {next_assignment.title}",
                    reason=f"This assignment is due in {days_until_due} day(s), so short-horizon planning should happen before deeper exploration.",
                    source="deadline",
                    recommended_action=recommended_action,
                    suggested_task_type="assignment_analysis",
                    queue_label="Analyze assignment",
                ),
                queue_mode="submit",
                task_type="assignment_analysis",
                task_title=f"Analyze assignment: {next_assignment.title}",
                task_summary=recommended_action,
                input_json={"assignment_id": str(next_assignment.id)},
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
        is_cancelled = failed_task.status == "cancelled"
        recommended_action = (
            f"Resume {failed_task.title} from its last checkpoint."
            if is_cancelled
            else f"Retry {failed_task.title} after checking why it {failed_task.status.replace('_', ' ')}."
        )
        return NextActionDecision(
            response=NextActionResponse(
                course_id=str(course_id),
                goal_id=str(failed_task.goal_id) if failed_task.goal_id else None,
                title=f"Recover task: {failed_task.title}",
                reason="The most recent durable task did not finish cleanly, so recovery is more valuable than starting unrelated work.",
                source="task_failure",
                recommended_action=recommended_action,
                suggested_task_type=failed_task.task_type,
                queue_label="Resume task" if is_cancelled else "Retry task",
            ),
            queue_mode="resume" if is_cancelled else "retry",
            existing_task_id=failed_task.id,
        )

    forecast = await predict_forgetting(db, user.id, course_id)
    risky_items = [
        item for item in forecast.get("predictions", [])
        if item.get("urgency") in {"overdue", "urgent", "warning"}
    ]
    if risky_items:
        top_item = risky_items[0]
        recommended_action = f"Review {top_item.get('title') or 'the at-risk material'} before its retrievability drops further."
        return NextActionDecision(
            response=NextActionResponse(
                course_id=str(course_id),
                goal_id=None,
                title=f"Refresh memory: {top_item.get('title') or 'course material'}",
                reason="The forgetting forecast shows material that is close to slipping below the retention threshold.",
                source="forgetting_risk",
                recommended_action=recommended_action,
                suggested_task_type="wrong_answer_review",
                queue_label="Queue review",
            ),
            queue_mode="submit",
            task_type="wrong_answer_review",
            task_title=f"Review at-risk material: {top_item.get('title') or 'course content'}",
            task_summary=recommended_action,
            input_json={"course_id": str(course_id)},
        )

    recommended_action = "Create a concrete study goal or ask the agent to generate a prioritized study plan."
    return NextActionDecision(
        response=NextActionResponse(
            course_id=str(course_id),
            goal_id=None,
            title="Set the next goal",
            reason="No active goal, deadline, failed task, or forgetting risk is currently dominating the queue.",
            source="manual",
            recommended_action=recommended_action,
            suggested_task_type="multi_step",
            queue_label="Generate plan",
        ),
        queue_mode="submit",
        task_type="multi_step",
        task_title="Generate prioritized study plan",
        task_summary=recommended_action,
        plan_prompt=recommended_action,
    )


@router.get("/{course_id}/next-action", response_model=NextActionResponse)
async def get_next_action(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    decision = await _resolve_next_action_decision(course_id=course_id, user=user, db=db)
    return decision.response


@router.post("/{course_id}/next-action/queue", response_model=AgentTaskResponse)
async def queue_next_action(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    decision = await _resolve_next_action_decision(course_id=course_id, user=user, db=db)

    if decision.queue_mode == "resume":
        task = await resume_task(decision.existing_task_id, user.id, db=db) if decision.existing_task_id else None
    elif decision.queue_mode == "retry":
        task = await retry_task(decision.existing_task_id, user.id, db=db) if decision.existing_task_id else None
    else:
        input_json = dict(decision.input_json or {})
        if decision.task_type == "multi_step":
            from services.agent.task_planner import create_plan

            prompt = decision.plan_prompt or decision.response.recommended_action
            steps = await create_plan(prompt, user.id, course_id)
            input_json.update({
                "course_id": str(course_id),
                "steps": steps,
                "plan_prompt": prompt,
            })

        task = await submit_task(
            user_id=user.id,
            db=db,
            course_id=course_id,
            goal_id=decision.goal_id,
            task_type=decision.task_type or decision.response.suggested_task_type or "multi_step",
            title=decision.task_title or decision.response.title,
            summary=decision.task_summary or decision.response.recommended_action,
            source="next_action",
            input_json=input_json,
            metadata_json={
                "next_action": decision.response.model_dump(),
                "queue_label": decision.response.queue_label,
            },
            requires_approval=False,
            max_attempts=2,
        )

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
    linked_task_count = int(count_result.scalar_one() or 0)
    return StudyGoalResponse(**serialize_model(goal, extra={"linked_task_count": linked_task_count}))
