"""Unit tests for ``services.welcome_back.compute_welcome_back`` (Phase 14 T4).

Seven cases pin the public contract the ``/api/sessions/welcome-back``
endpoint echoes to the frontend:

1. ``test_empty_history_returns_nulls`` — fresh account → every field
   goes to its zero form.
2. ``test_gap_zero_same_day`` — practice today → gap_days = 0.
3. ``test_gap_five_days_ago`` — last answer five days ago → gap_days=5.
4. ``test_top_mastered_returns_most_recent_three_correct`` — A/B/C/D
   problems with A,B,C correct (C most recent) + D incorrect →
   ``top_mastered_concepts == ["C", "B", "A"]``.
5. ``test_skips_null_content_node_id`` — correct answer on an
   un-rooted problem is ignored by the mastery list.
6. ``test_naive_and_aware_answered_at_both_work`` — parametrised on
   both tzinfo shapes; regression for the 2026-04-23 tz bug (SQLite
   strips tzinfo on ``DateTime(timezone=True)`` round-trip).
7. ``test_overdue_count_ignores_future_reviews`` — two past
   next_review_at + one future → overdue_count == 2.

We use a real SQLite aiosqlite engine per test, matching the
``test_freeze.py`` pattern. The AsyncMock dispatch used in
``test_daily_plan.py`` would need per-query SQL fragment matching and
wouldn't exercise the datetime round-trip that drives case (6).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from libs.datetime_utils import utcnow
from models.content import CourseContentTree
from models.course import Course
from models.practice import PracticeProblem, PracticeResult
from models.progress import LearningProgress
from models.user import User
from services.welcome_back import compute_welcome_back


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Isolated SQLite DB per test.

    Mirrors the ``test_freeze.py`` fixture: tempfile + aiosqlite +
    ``Base.metadata.create_all`` is fast enough per-test and dodges any
    cross-test pollution from a shared in-memory DB.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-welcome-", suffix=".db")
    os.close(fd)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _seed_user(db: AsyncSession, *, name: str = "WB Tester") -> User:
    user = User(name=name)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _seed_course(db: AsyncSession, user_id: uuid.UUID) -> Course:
    course = Course(name="WB Course", description="x", user_id=user_id)
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


async def _seed_content_node(
    db: AsyncSession, course_id: uuid.UUID, *, title: str
) -> CourseContentTree:
    node = CourseContentTree(
        course_id=course_id,
        title=title,
        level=1,
        order_index=0,
        source_type="manual",
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return node


async def _seed_problem(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
) -> PracticeProblem:
    problem = PracticeProblem(
        course_id=course_id,
        content_node_id=content_node_id,
        question_type="mc",
        question="Q?",
        options={"choices": ["a", "b"]},
        correct_answer="a",
        order_index=0,
    )
    db.add(problem)
    await db.commit()
    await db.refresh(problem)
    return problem


async def _seed_result(
    db: AsyncSession,
    *,
    problem_id: uuid.UUID,
    user_id: uuid.UUID,
    is_correct: bool,
    answered_at: datetime,
    user_answer: str = "a",
) -> PracticeResult:
    result = PracticeResult(
        problem_id=problem_id,
        user_id=user_id,
        user_answer=user_answer,
        is_correct=is_correct,
        answered_at=answered_at,
    )
    db.add(result)
    await db.commit()
    await db.refresh(result)
    return result


# ── 1. Empty history ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_history_returns_nulls(db_session: AsyncSession) -> None:
    """No PracticeResult rows → every summary field goes to its zero form."""

    user = await _seed_user(db_session)

    payload = await compute_welcome_back(db_session, user.id)

    assert payload.gap_days is None
    assert payload.last_practice_at is None
    assert payload.top_mastered_concepts == []
    assert payload.overdue_count == 0


# ── 2. Gap = 0 (same day) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_gap_zero_same_day(db_session: AsyncSession) -> None:
    """An answer today → gap_days = 0."""

    user = await _seed_user(db_session)
    course = await _seed_course(db_session, user.id)
    problem = await _seed_problem(db_session, course_id=course.id, content_node_id=None)

    # Anchor the result to today in UTC — any sub-second offset stays
    # inside the same UTC date.
    await _seed_result(
        db_session,
        problem_id=problem.id,
        user_id=user.id,
        is_correct=True,
        answered_at=utcnow(),
    )

    payload = await compute_welcome_back(db_session, user.id)

    assert payload.gap_days == 0
    assert payload.last_practice_at is not None


# ── 3. Gap = 5 days ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gap_five_days_ago(db_session: AsyncSession) -> None:
    """Last answer 5 days ago → gap_days = 5."""

    user = await _seed_user(db_session)
    course = await _seed_course(db_session, user.id)
    problem = await _seed_problem(db_session, course_id=course.id, content_node_id=None)

    five_days_ago = utcnow() - timedelta(days=5)
    await _seed_result(
        db_session,
        problem_id=problem.id,
        user_id=user.id,
        is_correct=True,
        answered_at=five_days_ago,
    )

    payload = await compute_welcome_back(db_session, user.id)

    assert payload.gap_days == 5


# ── 4. Top mastered: most recent 3 correct, in reverse order ───────


@pytest.mark.asyncio
async def test_top_mastered_returns_most_recent_three_correct(
    db_session: AsyncSession,
) -> None:
    """A, B, C correct (C most recent) + D incorrect → ["C", "B", "A"]."""

    user = await _seed_user(db_session)
    course = await _seed_course(db_session, user.id)

    # Titles line up 1:1 with node identity so assertions read naturally.
    node_a = await _seed_content_node(db_session, course.id, title="A")
    node_b = await _seed_content_node(db_session, course.id, title="B")
    node_c = await _seed_content_node(db_session, course.id, title="C")
    node_d = await _seed_content_node(db_session, course.id, title="D")

    p_a = await _seed_problem(
        db_session, course_id=course.id, content_node_id=node_a.id
    )
    p_b = await _seed_problem(
        db_session, course_id=course.id, content_node_id=node_b.id
    )
    p_c = await _seed_problem(
        db_session, course_id=course.id, content_node_id=node_c.id
    )
    p_d = await _seed_problem(
        db_session, course_id=course.id, content_node_id=node_d.id
    )

    # Correct answers ordered A (oldest) → B → C (most recent).
    now = utcnow()
    await _seed_result(
        db_session,
        problem_id=p_a.id,
        user_id=user.id,
        is_correct=True,
        answered_at=now - timedelta(hours=3),
    )
    await _seed_result(
        db_session,
        problem_id=p_b.id,
        user_id=user.id,
        is_correct=True,
        answered_at=now - timedelta(hours=2),
    )
    await _seed_result(
        db_session,
        problem_id=p_c.id,
        user_id=user.id,
        is_correct=True,
        answered_at=now - timedelta(hours=1),
    )
    # D answered most recently but wrong — must NOT appear.
    await _seed_result(
        db_session,
        problem_id=p_d.id,
        user_id=user.id,
        is_correct=False,
        answered_at=now - timedelta(minutes=5),
    )

    payload = await compute_welcome_back(db_session, user.id)

    assert payload.top_mastered_concepts == ["C", "B", "A"]


# ── 5. Skip null content_node_id ───────────────────────────────────


@pytest.mark.asyncio
async def test_skips_null_content_node_id(db_session: AsyncSession) -> None:
    """A correct answer on an un-rooted problem never lands in the mastery list."""

    user = await _seed_user(db_session)
    course = await _seed_course(db_session, user.id)

    # One rooted problem so we can prove the list has content when it
    # should, and one un-rooted problem that must be skipped.
    rooted_node = await _seed_content_node(db_session, course.id, title="RootedNode")
    p_rooted = await _seed_problem(
        db_session, course_id=course.id, content_node_id=rooted_node.id
    )
    p_orphan = await _seed_problem(
        db_session, course_id=course.id, content_node_id=None
    )

    now = utcnow()
    await _seed_result(
        db_session,
        problem_id=p_orphan.id,
        user_id=user.id,
        is_correct=True,
        answered_at=now - timedelta(minutes=1),  # most recent
    )
    await _seed_result(
        db_session,
        problem_id=p_rooted.id,
        user_id=user.id,
        is_correct=True,
        answered_at=now - timedelta(hours=1),  # older but rooted
    )

    payload = await compute_welcome_back(db_session, user.id)

    # Orphan is excluded even though its answered_at is most recent;
    # RootedNode remains.
    assert payload.top_mastered_concepts == ["RootedNode"]


# ── 6. Naive + aware answered_at both comparable ───────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "answered_at"),
    [
        (
            "naive",
            datetime.utcnow() - timedelta(days=2),  # naive UTC
        ),
        (
            "aware",
            datetime.now(timezone.utc) - timedelta(days=2),  # tz-aware UTC
        ),
    ],
)
async def test_naive_and_aware_answered_at_both_work(
    db_session: AsyncSession,
    label: str,
    answered_at: datetime,
) -> None:
    """Regression for 2026-04-23 tz bug: the compute step must not raise
    ``TypeError: can't compare offset-naive and offset-aware datetimes``
    regardless of whether the DB returned tzinfo on the round-trip.
    """

    user = await _seed_user(db_session)
    course = await _seed_course(db_session, user.id)
    problem = await _seed_problem(db_session, course_id=course.id, content_node_id=None)

    await _seed_result(
        db_session,
        problem_id=problem.id,
        user_id=user.id,
        is_correct=True,
        answered_at=answered_at,
    )

    payload = await compute_welcome_back(db_session, user.id)

    # Either shape of input produces the same ~2-day gap. Using >=1 /
    # <=3 instead of ==2 absorbs the rare case where the test straddles
    # midnight UTC between seed + compute.
    assert payload.gap_days is not None, label
    assert 1 <= payload.gap_days <= 3, f"{label}: gap_days={payload.gap_days}"
    assert payload.last_practice_at is not None, label
    # Normalised result must be tz-aware UTC regardless of input shape.
    assert payload.last_practice_at.tzinfo is not None, label


# ── 7. Overdue count ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_overdue_count_ignores_future_reviews(
    db_session: AsyncSession,
) -> None:
    """Two past next_review_at + one future → overdue_count == 2."""

    user = await _seed_user(db_session)
    course = await _seed_course(db_session, user.id)

    # Three distinct content nodes so LearningProgress rows don't
    # collide on (user_id, content_node_id) — the service counts
    # DISTINCT problem_id joined on content_node_id.
    node_x = await _seed_content_node(db_session, course.id, title="X")
    node_y = await _seed_content_node(db_session, course.id, title="Y")
    node_z = await _seed_content_node(db_session, course.id, title="Z")

    # Problems so the JOIN to practice_problems has matching rows.
    await _seed_problem(db_session, course_id=course.id, content_node_id=node_x.id)
    await _seed_problem(db_session, course_id=course.id, content_node_id=node_y.id)
    await _seed_problem(db_session, course_id=course.id, content_node_id=node_z.id)

    now = utcnow()
    db_session.add(
        LearningProgress(
            user_id=user.id,
            course_id=course.id,
            content_node_id=node_x.id,
            next_review_at=now - timedelta(days=3),
        )
    )
    db_session.add(
        LearningProgress(
            user_id=user.id,
            course_id=course.id,
            content_node_id=node_y.id,
            next_review_at=now - timedelta(hours=1),
        )
    )
    db_session.add(
        LearningProgress(
            user_id=user.id,
            course_id=course.id,
            content_node_id=node_z.id,
            next_review_at=now + timedelta(days=2),  # future — excluded
        )
    )
    await db_session.commit()

    payload = await compute_welcome_back(db_session, user.id)

    assert payload.overdue_count == 2
