"""Durable task/activity endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from libs.exceptions import ConflictError, NotFoundError, ValidationError
from models.agent_task import AgentTask
from models.user import User
from schemas.task import AgentTaskResponse, SubmitTaskRequest, TaskFollowUpResponse, TaskReviewResponse
from services.activity.engine import (
    TaskMutationError,
    approve_task,
    cancel_task,
    reject_task,
    resume_task,
    retry_task,
    submit_task,
)
from services.activity.task_records import serialize_task
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()


def _task_response(task: AgentTask) -> AgentTaskResponse:
    return AgentTaskResponse(**serialize_task(task))


def _completed_task_follow_up(task: AgentTask) -> TaskFollowUpResponse:
    task_review_payload = (task.result_json or {}).get("task_review")
    if not isinstance(task_review_payload, dict):
        raise ConflictError("This task does not have a completion review yet.")

    try:
        task_review = TaskReviewResponse.model_validate(task_review_payload)
    except PydanticValidationError as exc:
        raise ValidationError(f"Invalid task review payload: {exc.errors()[0]['msg']}") from exc

    follow_up = task_review.follow_up
    if not follow_up.ready:
        raise ConflictError("This task does not have a queueable follow-up.")
    return follow_up


@router.get("/", response_model=list[AgentTaskResponse])
async def list_tasks(
    course_id: uuid.UUID | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(AgentTask).where(AgentTask.user_id == user.id)
    if course_id:
        query = query.where(AgentTask.course_id == course_id)
    query = query.order_by(AgentTask.created_at.desc()).limit(limit)
    result = await db.execute(query)
    tasks = result.scalars().all()
    return [_task_response(task) for task in tasks]


@router.post("/submit", response_model=AgentTaskResponse, status_code=201)
async def submit_agent_task(
    body: SubmitTaskRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.course_id:
        await get_course_or_404(db, body.course_id, user_id=user.id)
    task = await submit_task(
        user_id=user.id,
        db=db,
        course_id=body.course_id,
        goal_id=body.goal_id,
        task_type=body.task_type,
        title=body.title,
        summary=body.summary,
        source=body.source,
        input_json=body.input_json,
        metadata_json=body.metadata_json,
        requires_approval=body.requires_approval,
        max_attempts=body.max_attempts,
    )
    request.state.audit_action_kind = "task_submit_http"
    request.state.audit_task_id = str(task.id)
    request.state.approval_status = task.approval_status
    return _task_response(task)


@router.post("/{task_id}/approve", response_model=AgentTaskResponse)
async def approve_agent_task(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await approve_task(task_id, user.id, db=db)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    request.state.audit_action_kind = "task_approve_http"
    request.state.audit_task_id = str(task.id)
    request.state.approval_status = task.approval_status
    return _task_response(task)


@router.post("/{task_id}/reject", response_model=AgentTaskResponse)
async def reject_agent_task(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await reject_task(task_id, user.id, db=db)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    request.state.audit_action_kind = "task_reject_http"
    request.state.audit_task_id = str(task.id)
    request.state.approval_status = task.approval_status
    return _task_response(task)


@router.post("/{task_id}/cancel", response_model=AgentTaskResponse)
async def cancel_agent_task(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await cancel_task(task_id, user.id, db=db)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    request.state.audit_action_kind = "task_cancel_http"
    request.state.audit_task_id = str(task.id)
    request.state.approval_status = task.approval_status
    return _task_response(task)


@router.post("/{task_id}/resume", response_model=AgentTaskResponse)
async def resume_agent_task(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await resume_task(task_id, user.id, db=db)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    request.state.audit_action_kind = "task_resume_http"
    request.state.audit_task_id = str(task.id)
    request.state.approval_status = task.approval_status
    return _task_response(task)


@router.post("/{task_id}/retry", response_model=AgentTaskResponse)
async def retry_agent_task(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        task = await retry_task(task_id, user.id, db=db)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    request.state.audit_action_kind = "task_retry_http"
    request.state.audit_task_id = str(task.id)
    request.state.approval_status = task.approval_status
    return _task_response(task)


@router.post("/{task_id}/follow-up", response_model=AgentTaskResponse)
async def queue_task_follow_up(
    task_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(AgentTask).where(AgentTask.id == task_id, AgentTask.user_id == user.id))
    task = result.scalar_one_or_none()
    if not task:
        raise NotFoundError("Task", task_id)
    if task.status != "completed":
        raise ConflictError("Follow-up can only be queued after a task completes.")

    follow_up = _completed_task_follow_up(task)

    course_id = task.course_id
    if course_id:
        await get_course_or_404(db, course_id, user_id=user.id)

    follow_up_task_type = str(follow_up.task_type or "").strip()
    follow_up_title = str(follow_up.title or "").strip()
    follow_up_summary = str(follow_up.summary or "").strip() or None
    input_json = dict(follow_up.input_json or {})

    if not follow_up_task_type or not follow_up_title:
        raise ConflictError("This task follow-up is incomplete and cannot be queued.")

    if follow_up_task_type == "multi_step" and not input_json.get("steps"):
        from services.agent.task_planner import create_plan

        if not course_id:
            raise ConflictError("Multi-step follow-up planning requires a course.")
        plan_prompt = str(follow_up.plan_prompt or follow_up_summary or follow_up_title).strip()
        steps = await create_plan(plan_prompt, user.id, course_id)
        input_json.update({
            "course_id": str(course_id),
            "steps": steps,
            "plan_prompt": plan_prompt,
        })
    elif course_id and "course_id" not in input_json:
        input_json["course_id"] = str(course_id)

    queued = await submit_task(
        user_id=user.id,
        db=db,
        course_id=course_id,
        goal_id=task.goal_id,
        task_type=follow_up_task_type,
        title=follow_up_title,
        summary=follow_up_summary,
        source="task_follow_up",
        input_json=input_json or None,
        metadata_json={
            "parent_task_id": str(task.id),
            "parent_task_title": task.title,
            "trigger": "completed_task_review",
            "queue_label": follow_up.label,
        },
        requires_approval=False,
        max_attempts=2,
    )
    request.state.audit_action_kind = "task_follow_up_http"
    request.state.audit_task_id = str(queued.id)
    request.state.approval_status = queued.approval_status
    return _task_response(queued)
