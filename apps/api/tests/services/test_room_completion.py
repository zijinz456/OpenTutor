"""Service tests for ``services.room_completion`` — Phase 16c Bundle B.

Covers the room-completion detector and its idempotent XP awarder.

Three groups:

1. ``is_room_complete`` — table-style cases for the four combinations
   (empty room, partial completion, full completion, wrong-only
   answers).
2. ``maybe_award_room_completion_xp`` — verifies the awarder is a
   no-op when the room is incomplete, awards on completion, dedups
   on a same-day replay, and applies the hacking multiplier when the
   parent path's ``track_id`` carries the ``"hacking"`` marker.

Harness mirrors ``tests/services/test_xp_service.py`` —
``sqlite+aiosqlite:///:memory:`` + ``StaticPool`` so the in-memory
``Base.metadata.create_all`` builds every table the awarder touches.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from models.xp_event import XpEvent  # noqa: F401 — register table on Base
from services.room_completion import (
    is_room_complete,
    maybe_award_room_completion_xp,
)
from services.xp_service import compute_xp


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Fresh in-memory SQLite per test (StaticPool keeps it alive)."""
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


async def _seed_path_and_room(
    session_factory,
    *,
    n_problems: int,
    track_id: str = "test_track",
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    """Seed user + course + path + one room with ``n_problems`` cards.

    Returns ``(user_id, course_id, room_id, problem_ids)``.
    """
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()
    path_id = uuid.uuid4()
    room_id = uuid.uuid4()
    problem_ids: list[uuid.UUID] = []

    async with session_factory() as db:
        db.add(User(id=user_id, name="Room Tester"))
        db.add(Course(id=course_id, user_id=user_id, name="Course"))
        db.add(
            LearningPath(
                id=path_id,
                slug=f"path-{path_id.hex[:8]}",
                title="Test Path",
                difficulty="beginner",
                track_id=track_id,
            )
        )
        db.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug="room-1",
                title="Test Room",
                room_order=0,
            )
        )
        for i in range(n_problems):
            pid = uuid.uuid4()
            problem_ids.append(pid)
            db.add(
                PracticeProblem(
                    id=pid,
                    course_id=course_id,
                    path_room_id=room_id,
                    task_order=i,
                    question_type="mc",
                    question=f"Q{i}",
                    correct_answer="a",
                )
            )
        await db.commit()

    return user_id, course_id, room_id, problem_ids


async def _record_result(
    session_factory,
    *,
    problem_id: uuid.UUID,
    user_id: uuid.UUID,
    is_correct: bool,
) -> None:
    """Insert a single PracticeResult — minimal happy-path attrs."""
    async with session_factory() as db:
        db.add(
            PracticeResult(
                id=uuid.uuid4(),
                problem_id=problem_id,
                user_id=user_id,
                user_answer="a" if is_correct else "wrong",
                is_correct=is_correct,
            )
        )
        await db.commit()


# ── 1. is_room_complete ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_room_complete_returns_false_when_no_problems(session_factory):
    """An empty room is never 'complete' — guard against awarding 0 XP."""
    user_id, _course_id, room_id, _ = await _seed_path_and_room(
        session_factory, n_problems=0
    )
    async with session_factory() as db:
        complete, total = await is_room_complete(
            db, user_id=user_id, path_room_id=room_id
        )
    assert complete is False
    assert total == 0


@pytest.mark.asyncio
async def test_is_room_complete_returns_false_when_partial(session_factory):
    """3 problems, only 2 answered correctly → not complete."""
    user_id, _course_id, room_id, pids = await _seed_path_and_room(
        session_factory, n_problems=3
    )
    await _record_result(
        session_factory, problem_id=pids[0], user_id=user_id, is_correct=True
    )
    await _record_result(
        session_factory, problem_id=pids[1], user_id=user_id, is_correct=True
    )
    # pids[2] is untouched.

    async with session_factory() as db:
        complete, total = await is_room_complete(
            db, user_id=user_id, path_room_id=room_id
        )
    assert complete is False
    assert total == 3


@pytest.mark.asyncio
async def test_is_room_complete_returns_true_when_all_correct(session_factory):
    """3 problems × 1 correct result each → complete."""
    user_id, _course_id, room_id, pids = await _seed_path_and_room(
        session_factory, n_problems=3
    )
    for pid in pids:
        await _record_result(
            session_factory, problem_id=pid, user_id=user_id, is_correct=True
        )

    async with session_factory() as db:
        complete, total = await is_room_complete(
            db, user_id=user_id, path_room_id=room_id
        )
    assert complete is True
    assert total == 3


@pytest.mark.asyncio
async def test_is_room_complete_ignores_wrong_answers(session_factory):
    """Problem with only is_correct=False results does NOT count as done."""
    user_id, _course_id, room_id, pids = await _seed_path_and_room(
        session_factory, n_problems=3
    )
    await _record_result(
        session_factory, problem_id=pids[0], user_id=user_id, is_correct=True
    )
    await _record_result(
        session_factory, problem_id=pids[1], user_id=user_id, is_correct=True
    )
    # Two wrong attempts on pid[2] — the room is still not complete.
    await _record_result(
        session_factory, problem_id=pids[2], user_id=user_id, is_correct=False
    )
    await _record_result(
        session_factory, problem_id=pids[2], user_id=user_id, is_correct=False
    )

    async with session_factory() as db:
        complete, total = await is_room_complete(
            db, user_id=user_id, path_room_id=room_id
        )
    assert complete is False
    assert total == 3


# ── 2. maybe_award_room_completion_xp ────────────────────────────────


@pytest.mark.asyncio
async def test_maybe_award_room_completion_xp_no_op_when_incomplete(
    session_factory,
):
    """Partial completion → returns None and inserts no xp_events row."""
    user_id, _course_id, room_id, pids = await _seed_path_and_room(
        session_factory, n_problems=3
    )
    await _record_result(
        session_factory, problem_id=pids[0], user_id=user_id, is_correct=True
    )

    async with session_factory() as db:
        evt = await maybe_award_room_completion_xp(
            db, user_id=user_id, path_room_id=room_id
        )
        await db.commit()
        assert evt is None

    async with session_factory() as db:
        count = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(XpEvent)
                .where(XpEvent.source_id == room_id)
            )
        ).scalar_one()
        assert count == 0


@pytest.mark.asyncio
async def test_maybe_award_room_completion_xp_awards_when_complete(
    session_factory,
):
    """Full completion → XpEvent inserted with the standard amount."""
    user_id, _course_id, room_id, pids = await _seed_path_and_room(
        session_factory, n_problems=3
    )
    for pid in pids:
        await _record_result(
            session_factory, problem_id=pid, user_id=user_id, is_correct=True
        )

    async with session_factory() as db:
        evt = await maybe_award_room_completion_xp(
            db, user_id=user_id, path_room_id=room_id
        )
        await db.commit()

    assert evt is not None
    # Standard room: 3 tasks × 10 = 30, well under the 100 cap.
    assert evt.amount == compute_xp(event_type="room_complete", task_count=3)
    assert evt.amount == 30
    assert evt.source == "room_complete"
    assert evt.source_id == room_id


@pytest.mark.asyncio
async def test_maybe_award_room_completion_xp_idempotent(session_factory):
    """Calling twice the same UTC day → second call returns None.

    The unique index on ``(user_id, source_id, date(earned_at))`` is the
    truth source; we only assert one xp_events row exists at the end.
    """
    user_id, _course_id, room_id, pids = await _seed_path_and_room(
        session_factory, n_problems=2
    )
    for pid in pids:
        await _record_result(
            session_factory, problem_id=pid, user_id=user_id, is_correct=True
        )

    async with session_factory() as db:
        first = await maybe_award_room_completion_xp(
            db, user_id=user_id, path_room_id=room_id
        )
        await db.commit()
        assert first is not None

        second = await maybe_award_room_completion_xp(
            db, user_id=user_id, path_room_id=room_id
        )
        await db.commit()
        # Same-day dedup → awarder returns None, helper passes it through.
        assert second is None

    async with session_factory() as db:
        count = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(XpEvent)
                .where(XpEvent.source_id == room_id)
            )
        ).scalar_one()
        assert count == 1


@pytest.mark.asyncio
async def test_maybe_award_room_completion_xp_hacking_multiplier(session_factory):
    """track_id containing 'hacking' triggers the ×2 multiplier path."""
    user_id, _course_id, room_id, pids = await _seed_path_and_room(
        session_factory,
        n_problems=4,
        track_id="hacking_foundations",
    )
    for pid in pids:
        await _record_result(
            session_factory, problem_id=pid, user_id=user_id, is_correct=True
        )

    async with session_factory() as db:
        evt = await maybe_award_room_completion_xp(
            db, user_id=user_id, path_room_id=room_id
        )
        await db.commit()

    assert evt is not None
    # Hacking: 4 × 20 = 80 (under the 200 cap).
    expected = compute_xp(event_type="hacking_room_complete", task_count=4)
    assert expected == 80
    assert evt.amount == expected
    assert evt.source == "hacking_room_complete"
    assert evt.source_id == room_id
