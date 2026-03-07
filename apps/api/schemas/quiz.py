"""Pydantic schemas for quiz endpoints."""

import uuid
from typing import Any

from pydantic import BaseModel, field_validator

from services.practice.annotation import normalize_question_options


class ExtractRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None
    count: int | None = None
    mode: str | None = None  # learning mode: course_following, self_paced, exam_prep, maintenance


class SubmitAnswerRequest(BaseModel):
    problem_id: uuid.UUID
    user_answer: str


class SaveGeneratedRequest(BaseModel):
    course_id: uuid.UUID
    raw_content: str
    title: str | None = None
    replace_batch_id: uuid.UUID | None = None


class ProblemResponse(BaseModel):
    id: uuid.UUID
    question_type: str
    question: str
    options: dict[str, str] | None
    order_index: int

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


class MasterySnapshotResponse(BaseModel):
    mastery_score: float
    gap_type: str | None
    content_node_id: str | None
    recorded_at: str
