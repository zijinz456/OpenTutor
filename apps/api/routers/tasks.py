"""Durable task/activity endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from libs.exceptions import ConflictError, NotFoundError
from models.agent_task import AgentTask
from models.user import User
from services.activity.engine import (
    TaskMutationError,
    approve_task,
    cancel_task,
    reject_task,
    resume_task,
    retry_task,
    submit_task,
)
from services.activity.tasks import serialize_task
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()


class AgentTaskResponse(BaseModel):
    id: str
    user_id: str
    course_id: str | None
    goal_id: str | None
    task_type: str
    status: str
    title: str
    summary: str | None
    source: str
    input_json: dict | None
    metadata_json: dict | None
    result_json: dict | None
    error_message: str | None
    attempts: int
    max_attempts: int
    requires_approval: bool
    task_kind: str
    risk_level: str
    approval_status: str
    checkpoint_json: dict | None
    step_results: list[dict]
    provenance: dict | None
    approved_at: str | None
    started_at: str | None
    cancel_requested_at: str | None
    created_at: str | None
    updated_at: str | None
    completed_at: str | None


class SubmitTaskRequest(BaseModel):
    task_type: str
    title: str
    course_id: uuid.UUID | None = None
    goal_id: uuid.UUID | None = None
    summary: str | None = None
    input_json: dict | None = None
    metadata_json: dict | None = None
    source: str = "workflow"
    requires_approval: bool = False
    max_attempts: int = 2


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
    return [AgentTaskResponse(**serialize_task(task)) for task in tasks]


@router.post("/submit", response_model=AgentTaskResponse, status_code=201)
async def submit_agent_task(
    body: SubmitTaskRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.course_id:
        await get_course_or_404(db, body.course_id, user_id=user.id)
    task = await submit_task(
        user_id=user.id,
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
    return AgentTaskResponse(**serialize_task(task))


@router.post("/{task_id}/approve", response_model=AgentTaskResponse)
async def approve_agent_task(task_id: uuid.UUID, user: User = Depends(get_current_user)):
    try:
        task = await approve_task(task_id, user.id)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    return AgentTaskResponse(**serialize_task(task))


@router.post("/{task_id}/reject", response_model=AgentTaskResponse)
async def reject_agent_task(task_id: uuid.UUID, user: User = Depends(get_current_user)):
    try:
        task = await reject_task(task_id, user.id)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    return AgentTaskResponse(**serialize_task(task))


@router.post("/{task_id}/cancel", response_model=AgentTaskResponse)
async def cancel_agent_task(task_id: uuid.UUID, user: User = Depends(get_current_user)):
    try:
        task = await cancel_task(task_id, user.id)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    return AgentTaskResponse(**serialize_task(task))


@router.post("/{task_id}/resume", response_model=AgentTaskResponse)
async def resume_agent_task(task_id: uuid.UUID, user: User = Depends(get_current_user)):
    try:
        task = await resume_task(task_id, user.id)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    return AgentTaskResponse(**serialize_task(task))


@router.post("/{task_id}/retry", response_model=AgentTaskResponse)
async def retry_agent_task(task_id: uuid.UUID, user: User = Depends(get_current_user)):
    try:
        task = await retry_task(task_id, user.id)
    except TaskMutationError as exc:
        raise ConflictError(str(exc)) from exc
    if not task:
        raise NotFoundError("Task", task_id)
    return AgentTaskResponse(**serialize_task(task))
