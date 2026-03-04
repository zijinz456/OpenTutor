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
    provider: str | None = None
    model: str | None = None
    llm_required: bool | None = None
    provider_keys: dict[str, str] | None = None
    base_url: str | None = None


class LlmConnectionTestRequest(BaseModel):
    provider: str
    model: str | None = None
    api_key: str | None = None


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
    created_at: str | None
    dismissed_at: str | None = None
    dismissal_reason: str | None = None


class PreferenceUpdateRequest(BaseModel):
    value: str | None = None
    scope: str | None = None
    source: str | None = None
    scene_type: str | None = None


class DismissRequest(BaseModel):
    reason: str | None = None


class MemoryProfileResponse(BaseModel):
    id: uuid.UUID
    summary: str
    memory_type: str
    category: str | None
    importance: float
    access_count: int
    source_message: str | None
    metadata_json: dict | None
    created_at: str | None
    updated_at: str | None
    dismissed_at: str | None = None
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
    summary: str | None = None
    category: str | None = None


class OllamaModelEntry(BaseModel):
    name: str
    size: int = 0
    modified_at: str = ""


class NLPreferenceRequest(BaseModel):
    text: str


class NLPreferenceResult(BaseModel):
    dimension: str | None = None
    value: str | None = None
    label: str | None = None
