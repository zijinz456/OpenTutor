"""Unit tests for the Python Depth drill-style branches of
``routers.quiz_submission.submit_answer`` (§16.2 + §26 Phase 3).

Covers the four drill styles:

1. ``trace``   — exact match after strip+lower (same contract as fill_blank).
2. ``apply``   — LLM-graded via ``services.practice.drill_grader``.
3. ``compare`` — LLM-graded via ``services.practice.drill_grader``.
4. ``rebuild`` — whitespace-tolerant exact match.

All tests stub the DB with ``AsyncMock`` + patched collaborators. The
LLM-grader tests monkey-patch ``services.practice.drill_grader._call_llm_once``
so we never hit Groq.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from models.practice import (
    QUESTION_TYPE_APPLY,
    QUESTION_TYPE_COMPARE,
    QUESTION_TYPE_REBUILD,
    QUESTION_TYPE_TRACE,
    PracticeProblem,
    PracticeResult,
)
from schemas.quiz import SubmitAnswerRequest

# ── fixtures / helpers ────────────────────────────────────────


def _user() -> SimpleNamespace:
    """Minimal stand-in for ``models.user.User`` — route only reads ``.id``."""
    return SimpleNamespace(id=uuid.uuid4())


def _problem(
    *,
    question_type: str,
    correct_answer: str,
    question: str = "Drill question text.",
) -> PracticeProblem:
    """Build a minimally-valid drill-style PracticeProblem.

    Populates only the attributes the submit_answer branch reads; the rest
    stay at SQLAlchemy defaults.
    """
    return PracticeProblem(
        id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        question_type=question_type,
        question=question,
        correct_answer=correct_answer,
        explanation="Reference explanation.",
        order_index=0,
        difficulty_layer=2,
    )


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
    """Neutralise collaborators the router invokes after the branch decision.

    These all make real DB / LLM calls the unit test can't satisfy — stub
    them out so the test exercises only the grading branch.
    """
    from services.progress import tracker as tracker_mod

    monkeypatch.setattr(tracker_mod, "update_quiz_result", AsyncMock(return_value=None))
    import services.analytics.events as events_mod

    monkeypatch.setattr(events_mod, "emit_quiz_answered", AsyncMock(return_value=None))

    # Error classification fires on wrong answers — stub so we don't hit Groq.
    import services.diagnosis.classifier as classifier_mod

    monkeypatch.setattr(
        classifier_mod,
        "classify_error",
        AsyncMock(return_value={"category": "conceptual"}),
    )


def _extract_practice_result(db: AsyncMock) -> PracticeResult | None:
    for call in db.add.call_args_list:
        obj = call.args[0]
        if isinstance(obj, PracticeResult):
            return obj
    return None


async def _call_submit(*, problem: PracticeProblem, user_answer: str) -> Any:
    """Drive ``submit_answer`` directly. Import inside so monkeypatches apply first."""
    from fastapi import BackgroundTasks

    from routers.quiz_submission import submit_answer

    db = _db_returning(problem)
    body = SubmitAnswerRequest(
        problem_id=problem.id,
        user_answer=user_answer,
        answer_time_ms=120,
    )
    bg = BackgroundTasks()
    response = await submit_answer(body=body, background_tasks=bg, user=_user(), db=db)
    return response, db


def _patch_drill_grader(
    monkeypatch: pytest.MonkeyPatch, *, passed: bool, explanation: str = "ok"
) -> None:
    """Replace the drill_grader's LLM transport with a scripted JSON response.

    Patching ``_call_llm_once`` (not ``grade_drill_answer``) exercises the
    real parser path — this catches regressions where the result schema
    changes but the router branch still thinks it has a verdict.
    """
    import json as _json

    response = _json.dumps(
        {"passed": passed, "explanation": explanation, "confidence": 0.9}
    )

    async def _fake_call(system_prompt: str, user_prompt: str) -> str | None:
        return response

    from services.practice import drill_grader as grader_mod

    monkeypatch.setattr(grader_mod, "_call_llm_once", _fake_call)


# ── tests ─────────────────────────────────────────────────────


def test_question_type_constants_exposed() -> None:
    """The 4 drill-style constants must be importable from models.practice and
    must have the exact string values the frontend / content pipeline expects.
    Pins the wire format so a rename breaks tests instead of silently
    invalidating every seeded card."""
    assert QUESTION_TYPE_TRACE == "trace"
    assert QUESTION_TYPE_APPLY == "apply"
    assert QUESTION_TYPE_COMPARE == "compare"
    assert QUESTION_TYPE_REBUILD == "rebuild"

    # And the canonical set — used by dispatch / validation.
    from models.practice import DRILL_STYLE_TYPES

    assert DRILL_STYLE_TYPES == frozenset({"trace", "apply", "compare", "rebuild"})


@pytest.mark.asyncio
async def test_trace_exact_match_grades_correctly() -> None:
    """Trace: user answer that matches expected stdout (modulo case/space)
    grades as correct."""
    problem = _problem(
        question_type=QUESTION_TYPE_TRACE,
        correct_answer="[1, 2, 3]",
        question="What does `print([1, 2, 3])` output?",
    )

    response, db = await _call_submit(problem=problem, user_answer="[1, 2, 3]")

    assert response.is_correct is True
    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is True


@pytest.mark.asyncio
async def test_trace_wrong_answer_grades_false() -> None:
    """Trace: mismatched output grades as wrong."""
    problem = _problem(
        question_type=QUESTION_TYPE_TRACE,
        correct_answer="[1, 2, 3]",
    )

    response, db = await _call_submit(problem=problem, user_answer="[1, 2]")

    assert response.is_correct is False
    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is False


@pytest.mark.asyncio
async def test_apply_llm_grading_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Apply: LLM grader returns passed=true → is_correct=true AND the
    grader's explanation is stored on PracticeResult.ai_explanation
    (substituted for the static problem.explanation)."""
    _patch_drill_grader(
        monkeypatch, passed=True, explanation="Correctly uses asyncio.gather."
    )
    reference = (
        "async def fetch_all(urls):\n"
        "    return await asyncio.gather(*[fetch(u) for u in urls])"
    )
    problem = _problem(
        question_type=QUESTION_TYPE_APPLY,
        correct_answer=reference,
        question="Rewrite the sync `fetch_all` using asyncio.",
    )

    response, db = await _call_submit(problem=problem, user_answer=reference)

    assert response.is_correct is True
    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is True
    assert pr.ai_explanation == "Correctly uses asyncio.gather."


@pytest.mark.asyncio
async def test_compare_llm_grading_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compare: LLM grader returns passed=true → is_correct=true. Same wiring
    as apply — validates the shared branch covers both types."""
    _patch_drill_grader(
        monkeypatch, passed=True, explanation="asyncio is I/O-bound-correct."
    )
    problem = _problem(
        question_type=QUESTION_TYPE_COMPARE,
        correct_answer=(
            "asyncio — the task is I/O-bound so threads add overhead "
            "without parallelism."
        ),
        question=(
            "Threads vs asyncio for 1000 concurrent HTTP requests — "
            "pick one and justify."
        ),
    )

    response, db = await _call_submit(
        problem=problem,
        user_answer="asyncio because the workload is network-bound.",
    )

    assert response.is_correct is True
    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is True
    assert pr.ai_explanation == "asyncio is I/O-bound-correct."


@pytest.mark.asyncio
async def test_rebuild_exact_match_after_whitespace_normalize() -> None:
    """Rebuild: trailing newline + leading/trailing blank lines are ignored
    when comparing filled code to the reference."""
    reference = "def add(a, b):\n    return a + b"
    problem = _problem(
        question_type=QUESTION_TYPE_REBUILD,
        correct_answer=reference,
        question="Fill the gap: `def add(a, b):\n    # TODO`",
    )

    # User's answer has:
    #   - a leading blank line
    #   - trailing whitespace on line 1
    #   - a trailing newline at EOF
    user_answer = "\ndef add(a, b):   \n    return a + b\n"

    response, db = await _call_submit(problem=problem, user_answer=user_answer)

    assert response.is_correct is True
    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is True
