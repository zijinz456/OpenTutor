"""Schemas for the LLM evaluation harness.

Defines the shapes consumed/produced by ``services.eval.runner`` and the
``scripts/run_eval.py`` CLI. Kept free of runtime deps (no DB models, no
async clients) so tests and YAML loaders can import cheaply.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


GradeMode = Literal["exact", "regex", "contains", "judge", "refusal"]


class EvalQuestion(BaseModel):
    """One graded prompt loaded from a YAML fixture."""

    id: str
    prompt: str
    expected: str
    grade_mode: GradeMode = "contains"
    category: str
    max_tokens: int = 500


class EvalResult(BaseModel):
    """Outcome of running a single ``EvalQuestion`` through the LLM router."""

    question_id: str
    category: str
    prompt: str
    expected: str
    actual: str
    passed: bool
    grade_mode: str
    latency_ms: int
    model: str
    # ``error`` is non-empty when the provider call itself failed
    # (network, rate-limit, schema error). Graded as passed=False.
    error: str | None = None


class EvalReport(BaseModel):
    """Aggregate result for one suite run. Machine-readable + printable."""

    model: str
    provider: str
    started_at: str  # ISO-8601 UTC timestamp
    duration_s: float
    total: int
    passed: int
    failed: int
    score_pct: float
    results: list[EvalResult] = Field(default_factory=list)
    category_scores: dict[str, float] = Field(default_factory=dict)
