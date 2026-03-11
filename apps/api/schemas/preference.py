"""Pydantic schemas for preference endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PreferenceCreate(BaseModel):
    dimension: str = Field(..., max_length=255)
    value: str = Field(..., max_length=1000)
    scope: str = Field(default="global", max_length=50)
    course_id: uuid.UUID | None = None
    source: str = Field(default="onboarding", max_length=100)


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


# ── LLM runtime config schemas ──


class LlmProviderStatus(BaseModel):
    provider: str
    has_key: bool
    masked_key: str | None = None
    requires_key: bool = True


class LlmRuntimeConfigResponse(BaseModel):
    provider: str
    model: str
    llm_required: bool
    providers: list[LlmProviderStatus]


class LlmRuntimeConfigUpdate(BaseModel):
    provider: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=255)
    llm_required: bool | None = None
    provider_keys: dict[str, str] | None = None
    base_url: str | None = Field(default=None, max_length=2048)


class LlmConnectionTestRequest(BaseModel):
    provider: str = Field(..., max_length=100)
    model: str | None = Field(default=None, max_length=255)
    api_key: str | None = Field(default=None, max_length=512)


class LlmConnectionTestResponse(BaseModel):
    provider: str
    model: str
    ok: bool
    response_preview: str
    usage: dict


# ── Signal & memory schemas ──


class PreferenceSignalResponse(BaseModel):
    id: uuid.UUID
    dimension: str
    value: str
    signal_type: str
    course_id: uuid.UUID | None
    context: dict | None
    created_at: datetime | None = None
    dismissed_at: datetime | None = None
    dismissal_reason: str | None = None


class PreferenceUpdateRequest(BaseModel):
    value: str | None = Field(default=None, max_length=1000)
    scope: str | None = Field(default=None, max_length=50)
    source: str | None = Field(default=None, max_length=100)
    scene_type: str | None = Field(default=None, max_length=100)


class DismissRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class MemoryProfileResponse(BaseModel):
    id: uuid.UUID
    summary: str
    memory_type: str
    category: str | None
    importance: float
    access_count: int
    source_message: str | None
    metadata_json: dict | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    dismissed_at: datetime | None = None
    dismissal_reason: str | None = None


class LearningProfileSummary(BaseModel):
    strength_areas: list[str]
    weak_areas: list[str]
    recurring_errors: list[str]
    inferred_habits: list[str]


class LearningProfileResponse(BaseModel):
    preferences: list[PreferenceResponse]
    dismissed_preferences: list[PreferenceResponse]
    signals: list[PreferenceSignalResponse]
    dismissed_signals: list[PreferenceSignalResponse]
    memories: list[MemoryProfileResponse]
    dismissed_memories: list[MemoryProfileResponse]
    summary: LearningProfileSummary


class MemoryUpdateRequest(BaseModel):
    summary: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=100)


class OllamaModelEntry(BaseModel):
    name: str
    size: int = 0
    modified_at: str = ""


class NLPreferenceRequest(BaseModel):
    text: str = Field(..., max_length=2000)


class NLPreferenceResult(BaseModel):
    dimension: str | None = None
    value: str | None = None
    label: str | None = None
