"""Pydantic schemas for course-related endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CourseCreate(BaseModel):
    name: str
    description: str | None = None


class CourseResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CourseOverviewCard(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime | None
    file_count: int
    content_node_count: int
    active_goal_count: int
    pending_task_count: int
    pending_approval_count: int
    last_agent_activity_at: datetime | None
    last_scene_id: str | None


class ContentNodeResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str | None
    level: int
    order_index: int
    source_type: str
    children: list["ContentNodeResponse"] = []

    model_config = {"from_attributes": True}
