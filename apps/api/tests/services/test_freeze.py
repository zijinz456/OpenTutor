"""Unit tests for ``services.freeze`` + the freeze-exclusion path in
``services.daily_plan.select_daily_plan`` (Phase 14 T1).

Covers the eight T1 service-level acceptance criteria:

1. ``test_freeze_card_creates_token`` — happy path, 24h expires_at.
2. ``test_freeze_over_quota_raises`` — 4th freeze in one week → 409.
3. ``test_freeze_same_card_twice_raises`` — lifetime uniqueness → 409.
4. ``test_can_freeze_returns_remaining`` — quota accounting.
5. ``test_can_freeze_resets_next_week`` — weekly boundary behavior.
6. ``test_active_frozen_problem_ids_expires`` — 24h expiry trims the list.
7. ``test_daily_plan_excludes_frozen`` — kwarg wiring on the selector.
8. ``test_alembic_upgrade_downgrade_roundtrip`` — table + index + unique
   constraint present after upgrade, dropped after downgrade.

Every DB test uses a real SQLite aiosqlite engine so the uniqueness
constraint and timestamp semantics get exercised — the selector unit
tests in ``test_daily_plan_strategy.py`` use AsyncMock; here we need
durability for the quota/uniqueness assertions.
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
from models.course import Course
from models.freeze_token import FreezeToken
from models.practice import PracticeProblem
from models.user import User
from services.daily_plan import select_daily_plan
from services.freeze import (
    FREEZE_EXPIRY_HOURS,
    FREEZE_QUOTA_PER_WEEK,
    ConflictError,
    active_frozen_problem_ids,
    can_freeze,
    freeze_card,
)


# Wednesday 2026-04-22 12:00 UTC — far enough from a week boundary that
# +1h / +25h shifts stay inside the same ISO week (Mon 2026-04-20 00:00
# UTC) and won't accidentally cross into the next quota bucket.
_NOW = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Per-test SQLite AsyncSession with all tables created via metadata.

    We skip Alembic for the service tests — ``Base.metadata.create_all``
    is enough to exercise the ORM contract and is ~20× faster than
    running the full migration stack. The Alembic round-trip lives in
    its own test below.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-freeze-", suffix=".db")
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


async def _seed_user_and_problem(db: AsyncSession) -> tuple[User, PracticeProblem]:
    """Persist a user + course + single practice problem so freeze rows
    satisfy the ``(user_id, problem_id)`` foreign keys."""

    user = User(name="Freeze Tester")
    db.add(user)
    await db.flush()

    course = Course(name="Freeze Course", description="x", user_id=user.id)
    db.add(course)
    await db.flush()

    problem = PracticeProblem(
        course_id=course.id,
        content_node_id=None,
        question_type="mc",
        question="Q?",
        options={"choices": ["a", "b"]},
        correct_answer="a",
        order_index=0,
    )
    db.add(problem)
    await db.commit()
    await db.refresh(user)
    await db.refresh(problem)
    return user, problem


async def _seed_problem(db: AsyncSession, course_id: uuid.UUID) -> PracticeProblem:
    """Add one more practice problem to ``course_id``."""

    problem = PracticeProblem(
        course_id=course_id,
        content_node_id=None,
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


# ── 1. Happy path — token created, 24h expiry ──────────────────────


@pytest.mark.asyncio
async def test_freeze_card_creates_token(db_session: AsyncSession) -> None:
    """freeze_card writes one row with expires_at = frozen_at + 24h."""

    user, problem = await _seed_user_and_problem(db_session)

    token = await freeze_card(db_session, user.id, problem.id, now=_NOW)

    assert token.user_id == user.id
    assert token.problem_id == problem.id
    # SQLite's DATETIME strips tzinfo on round-trip — compare naive
    # UTC components so the test works on both SQLite and Postgres.
    from libs.datetime_utils import as_utc

    assert as_utc(token.frozen_at) == _NOW
    assert as_utc(token.expires_at) == _NOW + timedelta(hours=FREEZE_EXPIRY_HOURS)
    # Sanity: active list must include this problem.
    active = await active_frozen_problem_ids(db_session, user.id, now=_NOW)
    assert problem.id in active


# ── 2. Weekly cap ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_freeze_over_quota_raises(db_session: AsyncSession) -> None:
    """4th freeze in one ISO week → ConflictError(weekly_cap_exceeded)."""

    user, _ = await _seed_user_and_problem(db_session)
    # _seed_user_and_problem already created one problem. We need 4 more
    # to exercise the 4th freeze (lifetime uniqueness would block the
    # same card from being frozen four times).
    p1 = await _seed_problem(db_session, (await _first_course(db_session)).id)
    p2 = await _seed_problem(db_session, (await _first_course(db_session)).id)
    p3 = await _seed_problem(db_session, (await _first_course(db_session)).id)
    p4 = await _seed_problem(db_session, (await _first_course(db_session)).id)

    # 3 freezes inside the quota
    await freeze_card(db_session, user.id, p1.id, now=_NOW)
    await freeze_card(db_session, user.id, p2.id, now=_NOW + timedelta(hours=1))
    await freeze_card(db_session, user.id, p3.id, now=_NOW + timedelta(hours=2))

    # 4th → 409
    with pytest.raises(ConflictError) as exc_info:
        await freeze_card(db_session, user.id, p4.id, now=_NOW + timedelta(hours=3))
    assert exc_info.value.reason == "weekly_cap_exceeded"


async def _first_course(db: AsyncSession) -> Course:
    """Helper — tests often only have one course and want to append
    more problems onto it."""

    from sqlalchemy import select

    result = await db.execute(select(Course).limit(1))
    course = result.scalar_one()
    return course


# ── 3. Per-card lifetime cap ───────────────────────────────────────


@pytest.mark.asyncio
async def test_freeze_same_card_twice_raises(db_session: AsyncSession) -> None:
    """UniqueConstraint: 2nd freeze on same (user, problem) → 409 already_frozen."""

    user, problem = await _seed_user_and_problem(db_session)

    await freeze_card(db_session, user.id, problem.id, now=_NOW)

    with pytest.raises(ConflictError) as exc_info:
        await freeze_card(
            db_session, user.id, problem.id, now=_NOW + timedelta(minutes=5)
        )
    assert exc_info.value.reason == "already_frozen"


# ── 4. Quota accounting ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_can_freeze_returns_remaining(db_session: AsyncSession) -> None:
    """After 2 freezes this week, remaining == quota - 2."""

    user, _ = await _seed_user_and_problem(db_session)
    course = await _first_course(db_session)
    p1 = await _seed_problem(db_session, course.id)
    p2 = await _seed_problem(db_session, course.id)

    await freeze_card(db_session, user.id, p1.id, now=_NOW)
    await freeze_card(db_session, user.id, p2.id, now=_NOW + timedelta(minutes=30))

    allowed, meta = await can_freeze(db_session, user.id, now=_NOW + timedelta(hours=1))
    assert allowed is True
    assert meta["quota"] == FREEZE_QUOTA_PER_WEEK
    assert meta["used"] == 2
    assert meta["remaining"] == FREEZE_QUOTA_PER_WEEK - 2


# ── 5. Weekly reset boundary ───────────────────────────────────────


@pytest.mark.asyncio
async def test_can_freeze_resets_next_week(db_session: AsyncSession) -> None:
    """3 freezes this week → remaining=0 now, remaining=3 next Monday."""

    user, _ = await _seed_user_and_problem(db_session)
    course = await _first_course(db_session)
    p1 = await _seed_problem(db_session, course.id)
    p2 = await _seed_problem(db_session, course.id)
    p3 = await _seed_problem(db_session, course.id)

    for i, p in enumerate([p1, p2, p3]):
        await freeze_card(db_session, user.id, p.id, now=_NOW + timedelta(minutes=i))

    _, meta_now = await can_freeze(db_session, user.id, now=_NOW)
    assert meta_now["remaining"] == 0

    # 8 days later — next week's Monday has passed → fresh bucket.
    next_week = _NOW + timedelta(days=8)
    _, meta_next = await can_freeze(db_session, user.id, now=next_week)
    assert meta_next["used"] == 0
    assert meta_next["remaining"] == FREEZE_QUOTA_PER_WEEK


# ── 6. Active-freeze expiry trimming ───────────────────────────────


@pytest.mark.asyncio
async def test_active_frozen_problem_ids_expires(db_session: AsyncSession) -> None:
    """After 25h the freeze is expired → active list is empty."""

    user, problem = await _seed_user_and_problem(db_session)
    await freeze_card(db_session, user.id, problem.id, now=_NOW)

    # Still active at +23h, expired at +25h.
    active_before = await active_frozen_problem_ids(
        db_session, user.id, now=_NOW + timedelta(hours=23)
    )
    assert problem.id in active_before

    active_after = await active_frozen_problem_ids(
        db_session, user.id, now=_NOW + timedelta(hours=25)
    )
    assert problem.id not in active_after
    assert active_after == []


# ── 7. Selector wiring — excluded_ids drops the frozen card ────────


@pytest.mark.asyncio
async def test_daily_plan_excludes_frozen(db_session: AsyncSession) -> None:
    """select_daily_plan(excluded_ids=[A.id]) → A not in returned cards."""

    user, problem_a = await _seed_user_and_problem(db_session)
    course = await _first_course(db_session)
    # Seed a second problem so the pool isn't empty when A is excluded.
    problem_b = await _seed_problem(db_session, course.id)
    _ = user  # consumed by helper; selector is global under single-user

    # With no exclusion both cards are candidates (they have no
    # LearningProgress + no failures so they'd be never-seen under
    # adhd_safe which drops never-seen rows — simulate a due row via
    # recently-failed fallback by stamping PracticeResult).
    from models.practice import PracticeResult

    # Fail A once so it lands in recent-fail tier; B will simply be
    # unselected by ADHD mode (never-seen, not due) — but that's fine,
    # we only need to prove "A out when excluded".
    db_session.add(
        PracticeResult(
            problem_id=problem_a.id,
            user_id=user.id,
            user_answer="b",
            is_correct=False,
            answered_at=_NOW - timedelta(hours=1),
        )
    )
    db_session.add(
        PracticeResult(
            problem_id=problem_b.id,
            user_id=user.id,
            user_answer="b",
            is_correct=False,
            answered_at=_NOW - timedelta(hours=2),
        )
    )
    await db_session.commit()

    # Baseline: both appear.
    plan_all = await select_daily_plan(db_session, size=5)
    all_ids = {c.id for c in plan_all.cards}
    assert problem_a.id in all_ids
    assert problem_b.id in all_ids

    # With A excluded: A out, B still present.
    plan_filtered = await select_daily_plan(
        db_session, size=5, excluded_ids=[problem_a.id]
    )
    filtered_ids = {c.id for c in plan_filtered.cards}
    assert problem_a.id not in filtered_ids
    assert problem_b.id in filtered_ids


# ── 8. Alembic round-trip ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_alembic_upgrade_downgrade_roundtrip() -> None:
    """Exercise the migration module's ``upgrade()`` and ``downgrade()``
    directly against a live SQLite connection.

    Note: this project's ``alembic/env.py`` short-circuits on SQLite
    (see comment there — "SQLite mode uses create_all()"), so driving
    the DDL via ``alembic command.upgrade`` is a no-op in tests.
    Instead we import the migration module, bind alembic's ``op`` to
    a real MigrationContext over our test DB, and invoke
    ``upgrade()``/``downgrade()`` — which is what the Postgres CI lane
    would do. Equivalent coverage of the DDL shape:

    * Table created with expected columns + constraints after upgrade.
    * Named index + unique constraint present.
    * Everything dropped after downgrade.
    * Re-upgrade is idempotent (no errors on re-create).
    """

    import importlib.util

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine
    from sqlalchemy import inspect as sa_inspect

    # Load the migration module by file path — the ``alembic/versions/``
    # dir is not a Python package (no ``__init__.py``), so
    # ``importlib.import_module`` can't find it. Spec-from-file is the
    # supported way Alembic itself loads revision scripts.
    repo_api = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    mig_path = os.path.join(
        repo_api, "alembic", "versions", "20260423_0002_freeze_tokens.py"
    )
    spec = importlib.util.spec_from_file_location("_mig_freeze_tokens", mig_path)
    assert spec is not None and spec.loader is not None
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)

    fd, db_path = tempfile.mkstemp(prefix="opentutor-freeze-alembic-", suffix=".db")
    os.close(fd)
    db_url = f"sqlite:///{db_path}"

    # The freeze migration FKs ``users`` and ``practice_problems``, so
    # those tables must exist. Run ``Base.metadata.create_all`` for
    # everything, then DROP freeze_tokens (if create_all made it), then
    # exercise the migration's upgrade/downgrade explicitly.
    engine = create_engine(db_url)

    try:
        Base.metadata.create_all(bind=engine)

        with engine.connect() as conn:
            # Drop freeze_tokens that create_all just made so the
            # migration's CREATE starts from a clean slate.
            conn.execute(FreezeToken.__table__.delete())
            FreezeToken.__table__.drop(bind=conn, checkfirst=True)
            conn.commit()

            insp = sa_inspect(conn)
            assert "freeze_tokens" not in insp.get_table_names()

            # Bind alembic ops to this connection + run upgrade().
            # ``Operations.context(MigrationContext)`` is the supported
            # way to drive a revision script outside ``alembic upgrade``.
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                mig.upgrade()

            insp = sa_inspect(conn)
            assert "freeze_tokens" in insp.get_table_names()
            idx_names = {i["name"] for i in insp.get_indexes("freeze_tokens")}
            assert "ix_freeze_tokens_user_expires" in idx_names
            uniques = insp.get_unique_constraints("freeze_tokens")
            unique_names = {u["name"] for u in uniques}
            # SQLite may surface a UniqueConstraint either as a
            # get_unique_constraints entry OR as a unique index —
            # accept either.
            assert (
                "uq_freeze_token_user_problem" in unique_names
                or "uq_freeze_token_user_problem" in idx_names
            )

            # Downgrade drops freeze_tokens cleanly.
            with Operations.context(ctx):
                mig.downgrade()
            insp = sa_inspect(conn)
            assert "freeze_tokens" not in insp.get_table_names()

            # Re-upgrade — round-trip completes without error.
            with Operations.context(ctx):
                mig.upgrade()
            insp = sa_inspect(conn)
            assert "freeze_tokens" in insp.get_table_names()
    finally:
        engine.dispose()
        try:
            os.unlink(db_path)
        except OSError:
            pass
