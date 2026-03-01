"""Pydantic schemas for preference endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class PreferenceCreate(BaseModel):
    dimension: str
    value: str
    scope: str = "global"
    course_id: uuid.UUID | None = None
    source: str = "onboarding"


class PreferenceResponse(BaseModel):
    id: uuid.UUID
    dimension: str
    value: str
    scope: str
    source: str
    confidence: float
    course_id: uuid.UUID | None
    dismissed_at: datetime | None = None
    dismissal_reason: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResolvedPreferences(BaseModel):
    """All resolved preferences for a given context (after cascade)."""
    preferences: dict[str, str]
    sources: dict[str, str]  # dimension → source scope
