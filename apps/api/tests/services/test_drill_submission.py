"""Tests for ``services.drill_submission.submit_drill`` (Phase 16c T8).

End-to-end orchestrator: runs the sandbox, writes ``drill_attempts``,
resolves next drill. These tests exercise the full stack including the
real subprocess runner — we use pure-Python drills (adding two ints) so
the runner cost is bounded and deterministic.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base

# Importing the models package registers every ORM table with
# ``Base.metadata`` — necessary so ``create_all`` produces the
# ``users`` / ``drill_attempts`` FK target tables.
import models  # noqa: F401
from models.drill import Drill, DrillAttempt, DrillCourse, DrillModule
from models.user import User
from services.drill_submission import NotFoundError, submit_drill


_HIDDEN_TESTS = (
    "from solution import add\n\ndef test_sum():\n    assert add(2, 3) == 5\n"
)
_CORRECT = "def add(a, b):\n    return a + b\n"
_WRONG = "def add(a, b):\n    return a - b\n"


@pytest_asyncio.fixture
async def session():
    """Fresh on-disk SQLite per test — see the note in
    ``test_drill_selector.py`` on why file-backed instead of ``:memory:``.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-drill-submission-", suffix=".db")
    os.close(fd)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as s:
        yield s
    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _seed_user(s: AsyncSession) -> uuid.UUID:
    u = User(name="Owner")
    s.add(u)
    await s.commit()
    await s.refresh(u)
    return u.id


async def _seed_one_drill_course(
    s: AsyncSession, *, drills_per_module: int = 1
) -> tuple[DrillCourse, list[Drill]]:
    course = DrillCourse(slug="c1", title="C", source="t", version="v1.0.0")
    s.add(course)
    await s.commit()
    await s.refresh(course)
    m = DrillModule(course_id=course.id, slug="m1", title="M1", order_index=1)
    s.add(m)
    await s.commit()
    await s.refresh(m)

    drills: list[Drill] = []
    for i in range(drills_per_module):
        d = Drill(
            module_id=m.id,
            slug=f"d{i + 1}",
            order_index=i + 1,
            title=f"Drill {i + 1}",
            why_it_matters="x",
            starter_code="def add(a, b):\n    ...\n",
            hidden_tests=_HIDDEN_TESTS,
            hints=[],
            skill_tags=[],
            source_citation="unit test",
            time_budget_min=1,
            difficulty_layer=1,
        )
        s.add(d)
        drills.append(d)
    await s.commit()
    for d in drills:
        await s.refresh(d)
    return course, drills


# ── Happy paths ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_pass_persists_attempt_and_returns_next(session: AsyncSession):
    user_id = await _seed_user(session)
    _, drills = await _seed_one_drill_course(session, drills_per_module=2)
    d1, d2 = drills

    result = await submit_drill(session, user_id, d1.id, _CORRECT)

    assert result.passed is True
    assert result.feedback == "Чисто! Тест пройдено."
    # next_drill_id should point at d2
    assert result.next_drill_id == str(d2.id)

    # A row was written
    attempts = (
        (
            await session.execute(
                select(DrillAttempt).where(DrillAttempt.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].passed is True
    assert attempts[0].drill_id == d1.id


@pytest.mark.asyncio
async def test_submit_fail_persists_attempt_and_null_next(session: AsyncSession):
    user_id = await _seed_user(session)
    _, drills = await _seed_one_drill_course(session, drills_per_module=2)
    d1, _ = drills

    result = await submit_drill(session, user_id, d1.id, _WRONG)

    assert result.passed is False
    assert result.feedback == "Ще не все — подивись на останній assert і спробуй ще."
    # No next_drill_id populated on failure
    assert result.next_drill_id is None

    attempts = (
        (
            await session.execute(
                select(DrillAttempt).where(DrillAttempt.user_id == user_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].passed is False


@pytest.mark.asyncio
async def test_submit_pass_on_last_drill_returns_null_next(session: AsyncSession):
    """Passing the final drill in a course → next_drill_id is None."""

    user_id = await _seed_user(session)
    _, drills = await _seed_one_drill_course(session, drills_per_module=1)
    (only,) = drills

    result = await submit_drill(session, user_id, only.id, _CORRECT)

    assert result.passed is True
    assert result.next_drill_id is None


# ── Error paths ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submit_unknown_drill_id_raises_not_found(session: AsyncSession):
    user_id = await _seed_user(session)
    await _seed_one_drill_course(session)

    with pytest.raises(NotFoundError) as exc_info:
        await submit_drill(session, user_id, uuid.uuid4(), _CORRECT)

    assert isinstance(exc_info.value.drill_id, uuid.UUID)
