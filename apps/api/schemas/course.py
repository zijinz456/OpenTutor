"""Pydantic schemas for course-related endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CourseWorkspaceFeatures(BaseModel):
    notes: bool = True
    practice: bool = True
    wrong_answer: bool = True
    study_plan: bool = True
    free_qa: bool = True


class CourseAutoScrapeSettings(BaseModel):
    enabled: bool = False
    interval_hours: int = 24


class CourseMetadata(BaseModel):
    workspace_features: CourseWorkspaceFeatures | None = None
    auto_scrape: CourseAutoScrapeSettings | None = None
    # Block layout persisted by frontend (/courses/{id}/layout endpoint)
    spaceLayout: dict[str, Any] | None = None
    # Optional explicit learning mode marker for dashboard fallback
    learning_mode: str | None = None

    # Preserve unknown metadata keys so frontend experiments don't get dropped.
    model_config = {"extra": "allow"}


class CourseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    metadata: CourseMetadata | None = None


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    metadata: CourseMetadata | None = None


class CourseResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    metadata: CourseMetadata | None = Field(
        default=None,
        validation_alias="metadata_",
        serialization_alias="metadata",
    )
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class CourseOverviewCard(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    metadata: CourseMetadata | None = None
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
    content_category: str | None = None
    children: list["ContentNodeResponse"] = []

    model_config = {"from_attributes": True}
