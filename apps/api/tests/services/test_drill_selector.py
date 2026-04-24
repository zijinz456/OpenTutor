"""Unit tests for ``services.drill_selector.select_next_drill`` (Phase 16c T7).

MVP semantics (deliberately dumb):
1. Walk modules in order_index asc, drills in order_index asc.
2. Return the first drill the user has NOT passed.
3. Return ``None`` when every drill is passed (course complete).
4. Return ``None`` for an unknown course slug.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base

# Importing the models package registers every ORM table with
# ``Base.metadata`` — necessary so ``create_all`` produces the
# ``users`` / ``drill_attempts`` FK target tables.
import models  # noqa: F401
from models.drill import Drill, DrillAttempt, DrillCourse, DrillModule
from models.user import User
from services.drill_selector import select_next_drill


@pytest_asyncio.fixture
async def session():
    """Fresh on-disk SQLite per test.

    A file-backed DB (not ``:memory:``) is used because an in-memory
    SQLite is scoped per-connection — the ``create_all`` connection
    and the subsequent session connections would each see a different
    empty DB. Mirrors the pattern in ``tests/routers/test_paths.py``.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-drill-selector-", suffix=".db")
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


async def _seed_course(s: AsyncSession, slug: str = "c1") -> DrillCourse:
    course = DrillCourse(slug=slug, title="C", source="t", version="v1.0.0")
    s.add(course)
    await s.commit()
    await s.refresh(course)
    return course


async def _seed_module(
    s: AsyncSession, course_id: uuid.UUID, slug: str, order: int
) -> DrillModule:
    m = DrillModule(course_id=course_id, slug=slug, title=slug, order_index=order)
    s.add(m)
    await s.commit()
    await s.refresh(m)
    return m


async def _seed_drill(
    s: AsyncSession, module_id: uuid.UUID, slug: str, order: int
) -> Drill:
    d = Drill(
        module_id=module_id,
        slug=slug,
        order_index=order,
        title=slug,
        why_it_matters="x",
        starter_code="",
        hidden_tests="",
        hints=[],
        skill_tags=[],
        source_citation="",
        time_budget_min=1,
        difficulty_layer=1,
    )
    s.add(d)
    await s.commit()
    await s.refresh(d)
    return d


@pytest.mark.asyncio
async def test_returns_first_drill_when_none_attempted(session: AsyncSession):
    user_id = await _seed_user(session)
    course = await _seed_course(session)
    m1 = await _seed_module(session, course.id, "m1", 1)
    d1 = await _seed_drill(session, m1.id, "d1", 1)
    await _seed_drill(session, m1.id, "d2", 2)

    result = await select_next_drill(session, user_id, "c1")

    assert result is not None
    assert result.id == d1.id


@pytest.mark.asyncio
async def test_skips_passed_drills(session: AsyncSession):
    user_id = await _seed_user(session)
    course = await _seed_course(session)
    m1 = await _seed_module(session, course.id, "m1", 1)
    d1 = await _seed_drill(session, m1.id, "d1", 1)
    d2 = await _seed_drill(session, m1.id, "d2", 2)

    # Mark d1 as passed
    session.add(
        DrillAttempt(user_id=user_id, drill_id=d1.id, passed=True, submitted_code="ok")
    )
    await session.commit()

    result = await select_next_drill(session, user_id, "c1")

    assert result is not None
    assert result.id == d2.id


@pytest.mark.asyncio
async def test_failed_attempts_do_not_count_as_passed(session: AsyncSession):
    """A failed attempt on d1 should NOT advance the selector past d1."""

    user_id = await _seed_user(session)
    course = await _seed_course(session)
    m1 = await _seed_module(session, course.id, "m1", 1)
    d1 = await _seed_drill(session, m1.id, "d1", 1)
    await _seed_drill(session, m1.id, "d2", 2)

    session.add(
        DrillAttempt(
            user_id=user_id, drill_id=d1.id, passed=False, submitted_code="nope"
        )
    )
    await session.commit()

    result = await select_next_drill(session, user_id, "c1")
    assert result is not None
    assert result.id == d1.id  # still the first unpassed drill


@pytest.mark.asyncio
async def test_walks_modules_in_order(session: AsyncSession):
    """Module order_index governs cross-module iteration."""

    user_id = await _seed_user(session)
    course = await _seed_course(session)
    # Insert m2 first to verify the sort uses order_index, not insert order
    m2 = await _seed_module(session, course.id, "m2", 2)
    m1 = await _seed_module(session, course.id, "m1", 1)

    d1 = await _seed_drill(session, m1.id, "d1", 1)
    d_m2 = await _seed_drill(session, m2.id, "d-m2", 1)

    # Pass m1/d1 — next should be m2/d-m2 (module order matters)
    session.add(
        DrillAttempt(user_id=user_id, drill_id=d1.id, passed=True, submitted_code="ok")
    )
    await session.commit()

    result = await select_next_drill(session, user_id, "c1")
    assert result is not None
    assert result.id == d_m2.id


@pytest.mark.asyncio
async def test_course_complete_returns_none(session: AsyncSession):
    user_id = await _seed_user(session)
    course = await _seed_course(session)
    m1 = await _seed_module(session, course.id, "m1", 1)
    d1 = await _seed_drill(session, m1.id, "d1", 1)

    session.add(
        DrillAttempt(user_id=user_id, drill_id=d1.id, passed=True, submitted_code="ok")
    )
    await session.commit()

    assert await select_next_drill(session, user_id, "c1") is None


@pytest.mark.asyncio
async def test_unknown_course_slug_returns_none(session: AsyncSession):
    user_id = await _seed_user(session)
    assert await select_next_drill(session, user_id, "no-such-course") is None


@pytest.mark.asyncio
async def test_empty_course_returns_none(session: AsyncSession):
    user_id = await _seed_user(session)
    await _seed_course(session, slug="empty")
    assert await select_next_drill(session, user_id, "empty") is None
