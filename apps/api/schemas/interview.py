"""Pydantic request/response schemas for the Interviewer Agent (Phase 5).

Kept separate from ``schemas/chat.py`` so the interview flow can evolve its
own rubric/feedback shapes without leaking them into the chat domain.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class InterviewStartRequest(BaseModel):
    """Payload for ``POST /interview/start``."""

    project_focus: str
    mode: Literal["behavioral", "technical", "code_defense", "mixed"]
    duration: Literal["quick", "standard", "deep"]
    course_id: UUID | None = None


class InterviewStartResponse(BaseModel):
    """First question + session handle returned by ``POST /interview/start``."""

    session_id: UUID
    question: str
    turn_number: int
    total_turns: int
    # e.g. ``star_stories.md#story-1`` / ``code_defense_drill.md#3ddepo`` /
    # ``generic`` when the corpus was too thin to ground on.
    grounding_source: str


class InterviewAnswerRequest(BaseModel):
    """Learner's typed answer for ``POST /interview/{id}/answer``."""

    answer_text: str


class DimensionScore(BaseModel):
    """One rubric dimension score — 1..5 plus ≤120-char feedback line."""

    score: int = Field(ge=1, le=5)
    feedback: str = Field(max_length=120)


class RubricScores(BaseModel):
    """Grader output for a single turn.

    ``dimensions`` keys are STAR (Situation/Task/Action/Result) for
    ``behavioral`` questions or Correctness/Depth/Tradeoff/Clarity for
    ``technical`` / ``code_defense``. Kept as ``dict`` so the schema can
    grow without a migration.
    """

    dimensions: dict[str, DimensionScore]
    feedback_short: str = Field(max_length=500)  # 2-3 sentences


class TurnResponse(BaseModel):
    """One turn inside a rehydrated session (``GET /interview/{id}``)."""

    turn_number: int
    question: str
    question_type: str
    grounding_source: str | None = None
    answer: str | None = None
    rubric: RubricScores | None = None
    answer_time_ms: int | None = None


class SummaryResponse(BaseModel):
    """Inline-math session summary — no LLM call, see ``write_summary_inline``."""

    avg_by_dimension: dict[str, float]
    weakest_dimensions: list[str]  # top 2 lowest-scoring dims
    worst_turn_id: UUID | None = None
    answer_time_ms_avg: int | None = None
    total_answer_time_s: int | None = None


class InterviewSessionStateResponse(BaseModel):
    """Full session rehydrate payload for pause/resume."""

    session_id: UUID
    status: Literal["in_progress", "completed", "completed_early", "abandoned"]
    mode: str
    duration: str
    project_focus: str
    total_turns: int
    completed_turns: int
    turns: list[TurnResponse]
    summary: SummaryResponse | None = None


class SaveGapsRequest(BaseModel):
    """Pick turns to distill into flashcards via §14.5 ``save-candidates``."""

    turn_ids: list[UUID] = Field(min_length=1, max_length=10)


class SaveGapsResponse(BaseModel):
    """Response for ``POST /interview/{id}/save-gaps``.

    Mirrors the shape of ``SaveCandidatesResponse`` from §14.5 but only
    exposes the two fields the frontend currently cares about for the
    interview "save gaps" toast — the spawned ``PracticeProblem.id``s and
    a precomputed count. The underlying ``GeneratedAsset.id`` is kept
    on the server side (cross-linked via ``problem_metadata``).
    """

    saved_count: int
    problem_ids: list[UUID]


class AbandonResponse(BaseModel):
    """Response for ``POST /interview/{id}/abandon``."""

    session_id: UUID
    summary: SummaryResponse
