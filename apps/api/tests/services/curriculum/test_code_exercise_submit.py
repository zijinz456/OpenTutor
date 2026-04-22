"""Unit tests for the code-exercise branch of ``routers.quiz_submission.submit_answer``
(§34.5 Phase 11 — Code Runner T1).

Covers the six observable branches required by the T1 plan:

1. **Happy path** — stdout matches ``expected_output`` → ``is_correct=true``
   and ``PracticeResult.user_answer`` stores the full JSON blob.
2. **Stdout mismatch** — wrong output → ``is_correct=false``.
3. **Normalizer "rstrip"** — trailing newline in user stdout is tolerated
   when the normalizer says so (this is the default).
4. **Syntax error** — stderr contains a traceback → ``is_correct=false``
   regardless of stdout (Q5=A decision, 2026-04-22).
5. **Feature flag off** — ``enable_code_exercises=False`` → submit raises
   ``ValidationError`` (mapped to HTTP 400 by the app-wide exception handler),
   no silent success.
6. **Missing expected_output** — metadata lacks the required key → submit
   raises ``ValidationError`` before attempting comparison.

All tests stub the DB with ``AsyncMock`` + patch the collaborators
(``update_quiz_result``, ``update_concept_mastery``, ``emit_quiz_answered``)
so the router can run without a real engine or LLM.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from libs.exceptions import ValidationError
from models.practice import CODE_EXERCISE_TYPE, PracticeProblem, PracticeResult
from schemas.quiz import SubmitAnswerRequest

# ── fixtures / helpers ────────────────────────────────────────


def _user() -> SimpleNamespace:
    """Minimal stand-in for ``models.user.User`` — route only reads ``.id``."""
    return SimpleNamespace(id=uuid.uuid4())


def _problem(
    *,
    expected_output: str | None = "[2, 4, 6]",
    stdout_normalizer: str | None = None,
    include_expected: bool = True,
) -> PracticeProblem:
    """Build a minimally-valid ``code_exercise`` PracticeProblem. Only the
    attributes the submit_answer branch reads are populated; the rest stay
    at their SQLAlchemy defaults (``None`` for nullable columns)."""
    metadata: dict[str, Any] = {
        "starter_code": "nums = [1, 2, 3]\n# your code here",
        "hints": ["Multiply each element by 2"],
    }
    if include_expected:
        metadata["expected_output"] = expected_output
    if stdout_normalizer is not None:
        metadata["stdout_normalizer"] = stdout_normalizer

    # We deliberately don't go through the DB — ``PracticeProblem(...)``
    # gives us an unmanaged instance that is legal to read attributes from.
    problem = PracticeProblem(
        id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        question_type=CODE_EXERCISE_TYPE,
        question="Double every element of ``nums`` and print the list.",
        correct_answer=None,  # code_exercise uses metadata.expected_output
        explanation=None,
        order_index=0,
        problem_metadata=metadata,
        difficulty_layer=2,
    )
    return problem


def _db_returning(problem: PracticeProblem) -> AsyncMock:
    """AsyncSession mock whose single ``db.execute(...)`` call returns
    ``problem`` via ``.scalar_one_or_none()``. Every downstream call inside
    ``submit_answer`` (update_quiz_result, classifier, etc.) is patched in
    the individual tests."""
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = problem

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result_proxy)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture(autouse=True)
def _patch_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the collaborators submit_answer calls after the branch
    decision. We test the branch logic — not the downstream FSRS / analytics
    paths (those have their own tests)."""
    from services.progress import tracker as tracker_mod

    monkeypatch.setattr(
        tracker_mod,
        "update_quiz_result",
        AsyncMock(return_value=None),
    )
    # ``services.analytics.events.emit_quiz_answered`` — swallow.
    import services.analytics.events as events_mod

    monkeypatch.setattr(events_mod, "emit_quiz_answered", AsyncMock(return_value=None))


@pytest.fixture(autouse=True)
def _enable_code_exercises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to feature ON for every test except the explicit flag-off one.
    The flag-off test overrides this fixture locally via its own monkeypatch."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "enable_code_exercises", True)


def _extract_practice_result(db: AsyncMock) -> PracticeResult | None:
    """Return the one ``PracticeResult`` added to the session, if any."""
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
    """Drive ``submit_answer`` directly. We import inside the helper to
    make sure any monkeypatch the test installed takes effect first."""
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


# ── tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_stdout_matches_marks_correct_and_persists_json() -> None:
    """1. User's stdout matches expected_output exactly → correct, and the
    full JSON payload (code + stdout + stderr + runtime_ms) is what's
    stored on ``PracticeResult.user_answer`` — so retrospectives can replay.
    """
    problem = _problem(expected_output="[2, 4, 6]")
    payload = {
        "code": "print([x*2 for x in [1,2,3]])",
        "stdout": "[2, 4, 6]",
        "stderr": "",
        "runtime_ms": 120,
    }

    response, db = await _call_submit(problem=problem, user_answer_payload=payload)

    assert response.is_correct is True

    pr = _extract_practice_result(db)
    assert pr is not None, "PracticeResult must be added to session"
    assert pr.is_correct is True
    # user_answer must be the full JSON — parseable and contains all four fields.
    stored = json.loads(pr.user_answer)
    assert stored == payload


@pytest.mark.asyncio
async def test_stdout_mismatch_marks_incorrect() -> None:
    """2. Wrong stdout → is_correct=false. Explanation is still returned."""
    problem = _problem(expected_output="[2, 4, 6]")
    payload = {
        "code": "print([x*2 for x in [1,2]])",
        "stdout": "[2, 4]",
        "stderr": "",
        "runtime_ms": 90,
    }

    response, db = await _call_submit(problem=problem, user_answer_payload=payload)

    assert response.is_correct is False
    pr = _extract_practice_result(db)
    assert pr is not None
    assert pr.is_correct is False


@pytest.mark.asyncio
async def test_rstrip_normalizer_tolerates_trailing_newline() -> None:
    """3. Default normalizer is "rstrip" — user's ``print()`` emits a trailing
    newline that shouldn't count against correctness.
    """
    problem = _problem(expected_output="[2, 4, 6]", stdout_normalizer="rstrip")
    payload = {
        "code": "print([2, 4, 6])",
        "stdout": "[2, 4, 6]\n",  # trailing \n from print()
        "stderr": "",
        "runtime_ms": 85,
    }

    response, _db = await _call_submit(problem=problem, user_answer_payload=payload)

    assert response.is_correct is True


@pytest.mark.asyncio
async def test_syntax_error_marks_incorrect_regardless_of_stdout() -> None:
    """4. Traceback in stderr → is_correct=false even if stdout happens to
    match (Q5=A: syntax errors are FSRS lapses)."""
    problem = _problem(expected_output="[2, 4, 6]")
    payload = {
        "code": "print([2, 4, 6)",  # unbalanced paren
        "stdout": "",
        "stderr": 'File "<exec>", line 1\n    print([2, 4, 6)\n                  ^\nSyntaxError: invalid syntax',
        "runtime_ms": 5,
    }

    response, _db = await _call_submit(problem=problem, user_answer_payload=payload)

    assert response.is_correct is False


@pytest.mark.asyncio
async def test_feature_flag_off_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """5. With ``enable_code_exercises=False``, submit refuses the request
    loudly (``ValidationError`` → 400) instead of silently marking correct
    or falling through to the MC branch."""
    from config import settings as app_settings

    monkeypatch.setattr(app_settings, "enable_code_exercises", False)

    problem = _problem(expected_output="[2, 4, 6]")
    payload = {
        "code": "print([2, 4, 6])",
        "stdout": "[2, 4, 6]",
        "stderr": "",
        "runtime_ms": 50,
    }

    with pytest.raises(ValidationError) as excinfo:
        await _call_submit(problem=problem, user_answer_payload=payload)

    assert "disabled" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_missing_expected_output_raises_validation_error() -> None:
    """6. Problem row missing ``expected_output`` in metadata → loud refusal
    BEFORE the comparison step."""
    problem = _problem(include_expected=False)
    payload = {
        "code": "print('anything')",
        "stdout": "anything",
        "stderr": "",
        "runtime_ms": 30,
    }

    with pytest.raises(ValidationError) as excinfo:
        await _call_submit(problem=problem, user_answer_payload=payload)

    assert "expected_output" in str(excinfo.value)


@pytest.mark.asyncio
async def test_invalid_payload_json_raises_validation_error() -> None:
    """Bonus: malformed JSON in user_answer → clean 400-mapped error, not a
    500. Protects the router from garbled client payloads."""
    problem = _problem(expected_output="[2, 4, 6]")

    with pytest.raises(ValidationError):
        await _call_submit(
            problem=problem,
            user_answer_payload="this is not json {",
        )
