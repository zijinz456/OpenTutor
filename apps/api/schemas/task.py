"""Pydantic schemas for durable task endpoints."""

import uuid

from pydantic import BaseModel, Field


class GoalUpdateResponse(BaseModel):
    goal_id: str
    title: str
    status: str
    current_milestone: str | None = None
    next_action: str | None = None


class TaskFollowUpResponse(BaseModel):
    ready: bool = False
    label: str | None = None
    task_type: str | None = None
    title: str | None = None
    summary: str | None = None
    input_json: dict | None = None
    plan_prompt: str | None = None


class TaskReviewResponse(BaseModel):
    status: str
    outcome: str
    blockers: list[str] = Field(default_factory=list)
    next_recommended_action: str | None = None
    follow_up: TaskFollowUpResponse = Field(default_factory=TaskFollowUpResponse)
    goal_update: GoalUpdateResponse | None = None


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
    approval_reason: str | None
    approval_action: str | None
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
