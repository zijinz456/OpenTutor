"""Durable task/activity endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from libs.exceptions import ConflictError, NotFoundError, ValidationError
from models.agent_task import AgentTask
from models.user import User
from schemas.task import AgentTaskResponse, SubmitTaskRequest
from services.activity.engine import (
    TaskMutationError,
    approve_task,
    cancel_task,
    reject_task,
    resume_task,
    submit_task,
)
from services.activity.task_records import serialize_task
from services.activity.task_types import SUPPORTED_TASK_TYPES
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()


def _task_response(task: AgentTask) -> AgentTaskResponse:
    return AgentTaskResponse(**serialize_task(task))


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
    if body.task_type not in SUPPORTED_TASK_TYPES:
        raise ValidationError(
            f"Unsupported task_type '{body.task_type}'. Supported: {', '.join(sorted(SUPPORTED_TASK_TYPES))}"
        )
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
