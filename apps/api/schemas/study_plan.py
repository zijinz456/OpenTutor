"""Response schemas for StudyPlan endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class StudyPlanResponse(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    name: str
    scene_id: Optional[str] = None
    tasks: dict
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
