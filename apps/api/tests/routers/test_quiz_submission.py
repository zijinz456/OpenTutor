"""Integration tests for Phase 16c Story 2 #4 card-XP wiring in
``routers.quiz_submission.submit_answer``.

Contract under test (Subagent A scope):

1. Submitting a CORRECT answer records one ``xp_events`` row with a
   positive ``amount`` (the ``compute_xp`` formula gives ≥ 1 for any
   ``correctness == 1.0`` regardless of layer).
2. Submitting a WRONG answer still records one ``xp_events`` row with
   the ``+1`` consolation amount (Story 2 #2 — anti "don't try" floor).
3. Submitting the SAME problem twice on the same UTC day inserts only
   ONE ``xp_events`` row (anti-spam UNIQUE index per Story 2 #3).
4. If ``award_card_xp`` raises (defensive — by contract it returns
   ``None`` on dedup, but a future bug could throw), the submit still
   returns 200 and the ``PracticeResult`` is still persisted.

Harness combines two existing patterns:

* In-memory SQLite + ``StaticPool`` from
  ``tests/services/test_xp_service.py`` — gives us a real DB so the
  partial unique index actually fires for case 3.
* Direct ``submit_answer`` invocation from
  ``tests/services/practice/test_drill_styles.py`` — bypasses the
  ASGI auth layer and noisy collaborators (analytics, classifier,
  progress tracker) which are stubbed.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.course import Course
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from models.xp_event import XpEvent  # noqa: F401  — register table on Base.metadata
from schemas.quiz import SubmitAnswerRequest


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Fresh in-memory SQLite per test (``StaticPool`` keeps it alive)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def seeded(session_factory):
    """Seed one user + one course + one fill-blank-style problem.

    Returns ``(user, course_id, problem_id)``. The problem uses the
    default exact-match grading branch so a matching ``user_answer``
    grades correct without needing any LLM/Pyodide stub.
    """
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    problem_id = uuid.uuid4()
    async with session_factory() as s:
        s.add(User(id=user_id, name="Owner"))
        s.add(Course(id=course_id, name="Python", description="t", user_id=user_id))
        s.add(
            PracticeProblem(
                id=problem_id,
                course_id=course_id,
                question_type="fill_blank",
                question="2 + 2 = ?",
                correct_answer="4",
                difficulty_layer=2,
                order_index=0,
            )
        )
        await s.commit()
    # Re-fetch a detached User instance the route can use as ``user`` arg.
    async with session_factory() as s:
        user = (await s.execute(sa.select(User).where(User.id == user_id))).scalar_one()
    return user, course_id, problem_id


@pytest.fixture(autouse=True)
def _stub_collaborators(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise downstream best-effort collaborators the route fires.

    These touch other services / external APIs the test can't satisfy —
    progress tracker writes to a different table tree, analytics emits
    a learning event, error classifier hits Groq. None of them are part
    of the Story 2 #4 contract under test, so stub them to no-ops.
    """
    from services.progress import tracker as tracker_mod

    monkeypatch.setattr(tracker_mod, "update_quiz_result", AsyncMock(return_value=None))

    import services.analytics.events as events_mod

    monkeypatch.setattr(events_mod, "emit_quiz_answered", AsyncMock(return_value=None))

    import services.diagnosis.classifier as classifier_mod

    monkeypatch.setattr(
        classifier_mod,
        "classify_error",
        AsyncMock(return_value={"category": "conceptual"}),
    )


# ── Helpers ──────────────────────────────────────────────────────────


async def _call_submit(
    *,
    db,
    user: User,
    problem_id: uuid.UUID,
    user_answer: str,
    answer_time_ms: int = 1234,
) -> Any:
    """Drive ``submit_answer`` against a real ``AsyncSession``."""
    # Imported here so ``_stub_collaborators`` patches apply before the
    # router's late imports resolve.
    from routers.quiz_submission import submit_answer

    body = SubmitAnswerRequest(
        problem_id=problem_id,
        user_answer=user_answer,
        answer_time_ms=answer_time_ms,
    )
    return await submit_answer(
        body=body, background_tasks=BackgroundTasks(), user=user, db=db
    )


async def _fetch_xp_events(session_factory, user_id: uuid.UUID) -> list[XpEvent]:
    async with session_factory() as s:
        rows = (
            (
                await s.execute(
                    sa.select(XpEvent)
                    .where(XpEvent.user_id == user_id)
                    .order_by(XpEvent.earned_at.asc())
                )
            )
            .scalars()
            .all()
        )
        return list(rows)


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_correct_answer_inserts_positive_xp_event(
    session_factory, seeded
) -> None:
    """Story 2 #4 — correct answer fires ``award_card_xp`` with +amount."""
    user, _, problem_id = seeded

    async with session_factory() as db:
        response = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="4"
        )

    assert response.is_correct is True
    events = await _fetch_xp_events(session_factory, user.id)
    assert len(events) == 1, f"expected 1 xp_event, got {len(events)}"
    # Layer=2, correctness=1.0, hints=0 → base 2 + no-hint bonus 1 = 3.
    # Fast-bonus also fires (answer_time_ms=1234 < 10s, layer >= 2) → 4.
    assert events[0].amount > 0
    assert events[0].source == "practice_result"
    assert events[0].source_id == problem_id


@pytest.mark.asyncio
async def test_wrong_answer_inserts_consolation_xp_event(
    session_factory, seeded
) -> None:
    """Story 2 #2 — wrong-but-attempted gets +1 consolation, not 0 / negative."""
    user, _, problem_id = seeded

    async with session_factory() as db:
        response = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="42"
        )

    assert response.is_correct is False
    events = await _fetch_xp_events(session_factory, user.id)
    assert len(events) == 1
    assert events[0].amount == 1, "wrong answer should award +1 consolation"
    assert events[0].source == "practice_result"


@pytest.mark.asyncio
async def test_same_problem_same_day_only_one_xp_event(session_factory, seeded) -> None:
    """Story 2 #3 — anti-spam UNIQUE index: only one event per
    (user, problem, UTC day). The second submit must NOT fail and the
    second ``PracticeResult`` MUST still persist."""
    user, _, problem_id = seeded

    async with session_factory() as db:
        await _call_submit(db=db, user=user, problem_id=problem_id, user_answer="4")
    async with session_factory() as db:
        response2 = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="4"
        )

    assert response2.is_correct is True

    events = await _fetch_xp_events(session_factory, user.id)
    assert len(events) == 1, (
        f"anti-spam UNIQUE index should dedupe; got {len(events)} events"
    )

    # Sanity: both PracticeResult rows landed despite the dedup.
    async with session_factory() as s:
        prs = (
            (
                await s.execute(
                    sa.select(PracticeResult).where(PracticeResult.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(prs) == 2, "both PracticeResults must persist"


@pytest.mark.asyncio
async def test_submit_succeeds_when_award_card_xp_raises(
    session_factory, seeded, monkeypatch
) -> None:
    """Story 2 #4 — defensive: if the awarder ever raises, the submit
    still returns and the ``PracticeResult`` is still persisted. The
    XP event is the only thing missing."""
    user, _, problem_id = seeded

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated awarder failure")

    import services.xp_service as xp_module

    monkeypatch.setattr(xp_module, "award_card_xp", _boom)

    async with session_factory() as db:
        response = await _call_submit(
            db=db, user=user, problem_id=problem_id, user_answer="4"
        )

    assert response.is_correct is True

    events = await _fetch_xp_events(session_factory, user.id)
    assert events == [], "no xp_event should land when awarder raises"

    # The PracticeResult write is the contract — it must NOT have been
    # rolled back by the awarder failure.
    async with session_factory() as s:
        prs = (
            (
                await s.execute(
                    sa.select(PracticeResult).where(PracticeResult.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(prs) == 1, "PracticeResult must persist when awarder raises"
