"""Pydantic schemas for quiz endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from services.practice.annotation import normalize_question_options


class ExtractRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None
    count: int | None = None
    mode: str | None = None  # learning mode: course_following, self_paced, exam_prep, maintenance
    difficulty: str | None = None  # easy | medium | hard


class SubmitAnswerRequest(BaseModel):
    problem_id: uuid.UUID
    user_answer: str = Field(..., max_length=5000)
    answer_time_ms: int | None = None  # Time from question display to answer submission


class SaveGeneratedRequest(BaseModel):
    course_id: uuid.UUID
    raw_content: str = Field(..., max_length=50000)
    title: str | None = Field(default=None, max_length=500)
    replace_batch_id: uuid.UUID | None = None


class QuizNodeFailureResponse(BaseModel):
    node_id: str | None = None
    title: str
    reason: str
    discarded_count: int = 0
    errors: list[str] = Field(default_factory=list)


class ExtractResponse(BaseModel):
    status: str
    problems_created: int
    validated_count: int = 0
    repaired_count: int = 0
    discarded_count: int = 0
    node_failures: list[QuizNodeFailureResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProblemResponse(BaseModel):
    id: uuid.UUID
    question_type: str
    question: str
    options: dict[str, str] | None
    order_index: int
    difficulty_layer: int | None = None
    problem_metadata: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, value: Any) -> dict[str, str] | None:
        return normalize_question_options(value)


class PrerequisiteGap(BaseModel):
    concept: str
    concept_id: str
    mastery: float
    gap_severity: float


class AnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str | None
    explanation: str | None
    prerequisite_gaps: list[PrerequisiteGap] | None = None
    warnings: list[str] = Field(default_factory=list)


class MasterySnapshotResponse(BaseModel):
    mastery_score: float
    gap_type: str | None
    content_node_id: str | None
    recorded_at: datetime


# ── CAT Pre-test ──

class PretestStartRequest(BaseModel):
    course_id: uuid.UUID


class PretestAnswerRequest(BaseModel):
    course_id: uuid.UUID
    concept_id: uuid.UUID
    correct: bool  # Frontend evaluates MC answer and sends boolean
