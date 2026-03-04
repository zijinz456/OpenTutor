"""Pydantic schemas for wrong answer endpoints."""

import uuid

from pydantic import BaseModel


class WrongAnswerResponse(BaseModel):
    id: uuid.UUID
    problem_id: uuid.UUID
    question: str | None = None
    question_type: str | None = None
    user_answer: str
    correct_answer: str | None
    explanation: str | None
    error_category: str | None
    diagnosis: str | None = None
    error_detail: dict | None = None
    knowledge_points: list | None
    review_count: int
    mastered: bool

    model_config = {"from_attributes": True}


class RetryRequest(BaseModel):
    user_answer: str


class RetryResponse(BaseModel):
    is_correct: bool
    correct_answer: str | None
    explanation: str | None
