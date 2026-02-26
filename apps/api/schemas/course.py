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

    model_config = {"from_attributes": True}


class ContentNodeResponse(BaseModel):
    id: uuid.UUID
    title: str
    content: str | None
    level: int
    order_index: int
    source_type: str
    children: list["ContentNodeResponse"] = []

    model_config = {"from_attributes": True}
