"""Pydantic schemas for quiz endpoints."""

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from services.practice.annotation import normalize_question_options


# §34.6 Phase 12 — localhost-only URL guard for lab screenshot evidence.
# Anchors the end with `(/|$)` so `http://localhost:8080.evil.com` and similar
# lookalike hostnames are rejected. Port digits are required — bare "localhost"
# won't match. Any external host is refused at the Pydantic layer so we never
# incur grader cost on obviously-bad input.
_LOCALHOST_URL_RE = re.compile(r"^http://localhost:\d+(/|$)")


class ExtractRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None
    count: int | None = None
    mode: str | None = None  # learning mode: course_following, self_paced, exam_prep, maintenance
    difficulty: str | None = None  # easy | medium | hard


class SubmitAnswerRequest(BaseModel):
    problem_id: uuid.UUID
    user_answer: str = Field(..., max_length=20000)
    answer_time_ms: int | None = None  # Time from question display to answer submission


class LabExerciseSubmitPayload(BaseModel):
    """Structured payload for hacking-lab answers (§34.6 Phase 12).

    When ``question_type == "lab_exercise"``, ``SubmitAnswerRequest.user_answer``
    is expected to be this object serialised as JSON. The router parses it,
    validates the screenshot URL (if any) is a localhost target, then hands the
    payload to ``services.practice.lab_grader.grade_lab_proof`` for LLM-rubric
    grading. The full JSON is persisted back into ``PracticeResult.user_answer``
    so retrospectives can replay the exact proof the user submitted.
    """

    payload_used: str = Field(
        ...,
        max_length=2000,
        description="Exact payload/input the user sent to the lab",
    )
    flag_or_evidence: str = Field(
        ...,
        max_length=2000,
        description="Flag string or description of observed behaviour",
    )
    screenshot_url: str | None = Field(
        default=None,
        max_length=500,
        description="Optional localhost URL to a screenshot of the solve",
    )

    @field_validator("screenshot_url")
    @classmethod
    def _screenshot_must_be_localhost(cls, value: str | None) -> str | None:
        """Reject anything that isn't a localhost URL.

        Users may only reference assets on their own machine — we never want
        the grader (or, more importantly, a future automated verifier) to
        reach out to an attacker-controlled URL. Blank/None is allowed — the
        field is optional.
        """
        if value is None or value == "":
            return value
        if not _LOCALHOST_URL_RE.match(value):
            raise ValueError(
                "screenshot_url must be a localhost URL (http://localhost:<port>/...)"
            )
        return value


class CodeExerciseSubmitPayload(BaseModel):
    """Structured payload for code-exercise answers (§34.5 Phase 11).

    When ``question_type == "code_exercise"``, ``SubmitAnswerRequest.user_answer``
    is expected to be this object serialised as JSON. The router parses it,
    compares ``stdout`` against the problem's ``expected_output``, and persists
    the full JSON back into ``PracticeResult.user_answer`` so retrospectives can
    replay the code the user actually wrote.
    """

    # Caps are chosen so a worst-case JSON envelope (~12 KB) stays comfortably
    # under SubmitAnswerRequest.user_answer's 20000-char limit.
    code: str = Field(..., max_length=5000, description="User's Python source")
    stdout: str = Field(default="", max_length=3000, description="Captured stdout")
    stderr: str = Field(default="", max_length=3000, description="Captured stderr")
    runtime_ms: int = Field(default=0, ge=0, description="Pyodide execution time")


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
