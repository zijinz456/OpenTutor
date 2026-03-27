"""Pydantic schemas for wrong answer endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class WrongAnswerResponse(BaseModel):
    id: uuid.UUID
    problem_id: uuid.UUID
    question: str | None = None
    question_type: str | None = None
    options: dict[str, str] | None = None
    user_answer: str
    correct_answer: str | None
    explanation: str | None
    error_category: str | None
    diagnosis: str | None = None
    error_detail: dict | None = None
    knowledge_points: list | None
    review_count: int
    mastered: bool
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class RetryRequest(BaseModel):
    user_answer: str


class RetryResponse(BaseModel):
    is_correct: bool
    correct_answer: str | None
    explanation: str | None


class DeriveResponse(BaseModel):
    problem_id: str
    original_problem_id: str
    question: str | None = None
    question_type: str | None = None
    options: dict | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    is_diagnostic: bool = True
    simplifications_made: list[str] = []
    core_concept_preserved: str = ""


class DiagnoseResponse(BaseModel):
    diagnosis: str | None = None
    original_correct: bool | None = None
    clean_correct: bool | None = None
    interpretation: str | None = None
    status: str | None = None
    message: str | None = None
    diagnostic_problem_id: str | None = None


class WrongAnswerStatsResponse(BaseModel):
    total: int
    mastered: int
    unmastered: int
    by_category: dict[str, int]
    by_diagnosis: dict[str, int]
