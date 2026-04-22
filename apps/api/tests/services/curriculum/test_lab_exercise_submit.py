"""Unit tests for the lab-exercise branch of ``routers.quiz_submission.submit_answer``
(§34.6 Phase 12 Hacking Labs — T2).

Covers the five branches required by the T2 plan:

1. **Happy path** — grader returns ``{passed:true, ...}`` → ``is_correct=true``,
   and ``PracticeResult.user_answer`` contains both the payload and the grader
   verdict repacked as JSON; ``ai_explanation`` is the grader's one-liner.
2. **External URL screenshot** — ``screenshot_url="http://evil.com"`` raises
   ``ValidationError`` BEFORE the grader is ever called.
3. **Feature flag off** — ``enable_hacking_labs=False`` → submit raises
   ``ValidationError``; grader not called.
4. **Malformed JSON twice** — grader returns garbage twice → fallback to
   ``passed=False, confidence=0.0``; no exception leaks.
5. **Transport error** — grader's LLM client raises → fallback (same as #4);
   no exception leaks.

All tests stub the DB (``AsyncMock`` + patched collaborators) and monkey-patch
the grader's ``get_llm_client`` / ``_call_llm_once`` so we never hit Groq.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from libs.exceptions import ValidationError
from models.practice import LAB_EXERCISE_TYPE, PracticeProblem, PracticeResult
from schemas.quiz import SubmitAnswerRequest

# ── fixtures / helpers ────────────────────────────────────────


def _user() -> SimpleNamespace:
    """Minimal stand-in for ``models.user.User`` — route only reads ``.id``."""
    return SimpleNamespace(id=uuid.uuid4())


def _problem(
    *,
    expected_artifact_type: str = "reflected XSS payload",
) -> PracticeProblem:
    """Build a minimally-valid ``lab_exercise`` PracticeProblem."""
    metadata: dict[str, Any] = {
        "target_url": "http://localhost:3100/",
        "lab_type": "xss",
        "expected_artifact_type": expected_artifact_type,
    }
    problem = PracticeProblem(
        id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        question_type=LAB_EXERCISE_TYPE,
        question="Exploit a reflected XSS on the Juice Shop search endpoint.",
        correct_answer=None,
        explanation=None,
        order_index=0,
        problem_metadata=metadata,
        difficulty_layer=2,
    )
    return problem


def _db_returning(problem: PracticeProblem) -> AsyncMock:
    """AsyncSession mock returning the single problem row."""
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = problem

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _patch_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise collaborators the router invokes after the branch decision."""
    from services.progress import tracker as tracker_mod

    monkeypatch.setattr(tracker_mod, "update_quiz_result", AsyncMock(return_value=None))
    import services.analytics.events as events_mod

    monkeypatch.setattr(events_mod, "emit_quiz_answered", AsyncMock(return_value=None))


@pytest.fixture(autouse=True)
def _enable_hacking_labs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: feature ON. The flag-off test overrides locally."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "enable_hacking_labs", True)


def _extract_practice_result(db: AsyncMock) -> PracticeResult | None:
    for call in db.add.call_args_list:
        obj = call.args[0]
        if isinstance(obj, PracticeResult):
            return obj
    return None


async def _call_submit(
    *,
    problem: PracticeProblem,
    user_answer_payload: dict[str, Any] | str,
) -> Any:
    """Drive ``submit_answer`` directly. Import inside so monkeypatches apply first."""
    from fastapi import BackgroundTasks

    from routers.quiz_submission import submit_answer

    db = _db_returning(problem)
    body = SubmitAnswerRequest(
        problem_id=problem.id,
        user_answer=(
            user_answer_payload
            if isinstance(user_answer_payload, str)
            else json.dumps(user_answer_payload)
        ),
        answer_time_ms=120,
    )
    bg = BackgroundTasks()
    response = await submit_answer(body=body, background_tasks=bg, user=_user(), db=db)
    return response, db


def _patch_grader_llm(
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses: list[str | None],
) -> list[tuple[str, str]]:
    """Replace ``lab_grader._call_llm_once`` with a scripted sequence.

    Returns a list that gets populated with (system, user) tuples so the test
    can assert call count / prompt content. ``None`` entries simulate a
    transport error (the real helper catches and returns ``None``).
    """
    calls: list[tuple[str, str]] = []
    iter_responses = iter(responses)

    async def _fake_call(system_prompt: str, user_prompt: str) -> str | None:
        calls.append((system_prompt, user_prompt))
        try:
            return next(iter_responses)
        except StopIteration:
            return None

    from services.practice import lab_grader as grader_mod

    monkeypatch.setattr(grader_mod, "_call_llm_once", _fake_call)
    return calls


# ── tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_grader_passes_stores_repacked_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1. Grader returns ``passed=true`` → ``is_correct=true``; PracticeResult
    stores the full repacked JSON (payload + grader verdict) and uses the
    grader's explanation for ``ai_explanation``."""
    calls = _patch_grader_llm(
        monkeypatch,
        responses=[
            json.dumps(
                {
                    "passed": True,
                    "explanation": "Payload is a valid reflected XSS vector.",
                    "confidence": 0.92,
                }
            )
        ],
    )
    problem = _problem()
    payload = {
        "payload_used": "<script>alert(1)</script>",
        "flag_or_evidence": "Alert fired on the search results page; reflected.",
        "screenshot_url": "http://localhost:3100/rest/products/search",
    }

    response, db = await _call_submit(problem=problem, user_answer_payload=payload)

    assert response.is_correct is True
    assert len(calls) == 1, "grader must be called exactly once on happy path"

    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is True
    stored = json.loads(pr.user_answer)
    assert stored["payload_used"] == payload["payload_used"]
    assert stored["flag_or_evidence"] == payload["flag_or_evidence"]
    assert stored["screenshot_url"] == payload["screenshot_url"]
    assert stored["grader"]["passed"] is True
    assert stored["grader"]["confidence"] == 0.92
    assert pr.ai_explanation == "Payload is a valid reflected XSS vector."


@pytest.mark.asyncio
async def test_external_screenshot_url_rejected_before_grader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2. External ``screenshot_url`` → ``ValidationError`` at payload parse;
    the grader's LLM is NEVER called, so no cost is incurred."""
    calls = _patch_grader_llm(monkeypatch, responses=[])  # would fail if reached
    problem = _problem()
    payload = {
        "payload_used": "<script>alert(1)</script>",
        "flag_or_evidence": "popup fired",
        "screenshot_url": "http://evil.com/steal",
    }

    with pytest.raises(ValidationError) as excinfo:
        await _call_submit(problem=problem, user_answer_payload=payload)

    assert "screenshot_url" in str(excinfo.value) or "localhost" in str(excinfo.value)
    assert calls == [], "grader must NOT be called when URL validation fails"


@pytest.mark.asyncio
async def test_feature_flag_off_raises_before_grader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3. ``enable_hacking_labs=False`` → 400 at the gate; grader not called."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "enable_hacking_labs", False)
    calls = _patch_grader_llm(monkeypatch, responses=[])  # would fail if reached

    problem = _problem()
    payload = {
        "payload_used": "<script>alert(1)</script>",
        "flag_or_evidence": "popup fired",
        "screenshot_url": None,
    }

    with pytest.raises(ValidationError) as excinfo:
        await _call_submit(problem=problem, user_answer_payload=payload)

    assert "disabled" in str(excinfo.value).lower()
    assert calls == [], "grader must NOT be called when feature flag is off"


@pytest.mark.asyncio
async def test_grader_malformed_json_twice_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """4. Grader returns garbage twice → fallback verdict (passed=false,
    confidence=0.0, explanation="grader unavailable"). No exception leaks."""
    calls = _patch_grader_llm(
        monkeypatch,
        responses=["not json at all", "also not { json"],
    )
    problem = _problem()
    payload = {
        "payload_used": "<script>alert(1)</script>",
        "flag_or_evidence": "popup fired",
        "screenshot_url": None,
    }

    response, db = await _call_submit(problem=problem, user_answer_payload=payload)

    assert response.is_correct is False
    assert len(calls) == 2, "grader should retry exactly once on malformed JSON"

    pr = _extract_practice_result(db)
    assert pr is not None
    stored = json.loads(pr.user_answer)
    assert stored["grader"]["passed"] is False
    assert stored["grader"]["confidence"] == 0.0
    assert stored["grader"]["explanation"] == "grader unavailable"
    assert pr.ai_explanation == "grader unavailable"


@pytest.mark.asyncio
async def test_grader_transport_error_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5. Grader's LLM client produces None (transport error) → fallback;
    no exception reaches the caller."""
    calls = _patch_grader_llm(monkeypatch, responses=[None])
    problem = _problem()
    payload = {
        "payload_used": "<script>alert(1)</script>",
        "flag_or_evidence": "popup fired",
        "screenshot_url": None,
    }

    response, db = await _call_submit(problem=problem, user_answer_payload=payload)

    assert response.is_correct is False
    assert len(calls) == 1, "transport error short-circuits before retry"

    pr = _extract_practice_result(db)
    assert pr is not None
    stored = json.loads(pr.user_answer)
    assert stored["grader"]["passed"] is False
    assert stored["grader"]["explanation"] == "grader unavailable"
