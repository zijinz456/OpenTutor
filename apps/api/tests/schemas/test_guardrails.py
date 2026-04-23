"""Tests for Phase 7 Guardrails T1 — config flags + ChatRequest extension +
``GuardrailsOutput`` pydantic schema.

Only covers the foundational T1 scope (no tutor.py / turn_pipeline
integration yet — those land in T2 / T3).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from config import Settings
from schemas.chat import ChatRequest
from schemas.guardrails import GuardrailsOutput


def test_settings_default_guardrails_flag_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default config — strict mode OFF, min_score calibration placeholder."""
    # Clear any ambient env that would flip the default in CI.
    monkeypatch.delenv("GUARDRAILS_STRICT", raising=False)
    monkeypatch.delenv("GUARDRAILS_RETRIEVAL_MIN_SCORE", raising=False)

    s = Settings(_env_file=None)  # type: ignore[call-arg]

    assert s.guardrails_strict is False
    assert s.guardrails_retrieval_min_score == pytest.approx(0.62)


def test_settings_env_override_guardrails_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GUARDRAILS_STRICT=true in env flips the flag on."""
    monkeypatch.setenv("GUARDRAILS_STRICT", "true")

    s = Settings(_env_file=None)  # type: ignore[call-arg]

    assert s.guardrails_strict is True


def test_chat_request_accepts_guardrails_strict_field() -> None:
    """ChatRequest opt-in override is accepted; omission keeps it None
    (backward-compat — routing layer falls back to settings).
    """
    course_id = uuid.uuid4()

    req_with = ChatRequest(
        course_id=course_id,
        message="hello",
        guardrails_strict=True,
    )
    assert req_with.guardrails_strict is True

    req_without = ChatRequest(course_id=course_id, message="hello")
    assert req_without.guardrails_strict is None


def test_guardrails_output_schema_validates_confidence_range() -> None:
    """confidence is constrained to 1..5 inclusive."""
    # Valid — boundary
    ok = GuardrailsOutput(answer="x", confidence=5, citations=[1])
    assert ok.confidence == 5

    # Below range
    with pytest.raises(ValidationError):
        GuardrailsOutput(answer="x", confidence=0, citations=[])

    # Above range
    with pytest.raises(ValidationError):
        GuardrailsOutput(answer="x", confidence=6, citations=[])


def test_guardrails_output_citations_accepts_empty_list() -> None:
    """Refusal path emits an empty citations list — must validate."""
    out = GuardrailsOutput(answer="x", confidence=1, citations=[])

    assert out.citations == []
    assert out.answer == "x"
