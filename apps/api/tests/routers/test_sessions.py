"""Integration tests for ``GET /api/sessions/daily-plan`` ``strategy``
query wiring (Phase 14 T5, Story 5).

Covers the three router-level acceptance criteria for bad-day mode:

1. ``test_daily_plan_easy_only_returns_200`` — a valid bad-day request
   returns HTTP 200 and a :class:`schemas.sessions.DailyPlan` shape.
2. ``test_daily_plan_struggle_first_rejected`` — the internal brutal
   strategy must NOT be reachable from the public daily endpoint; 422
   from the pydantic ``Literal`` validator.
3. ``test_daily_plan_invalid_strategy_rejected`` — unknown strategy
   values also yield 422.

Fixture cloned from ``test_sessions_welcome.py`` — isolated SQLite DB
per test with ``get_db`` overridden, ``ASGITransport`` in-process client.
Single-user mode (default) keeps the auth dependency transparent.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from models.course import Course
from models.practice import PracticeProblem
from models.user import User


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client_with_db():
    """Per-test ``AsyncClient`` + session factory. Isolated SQLite file
    keeps cross-test state out of the way — the bad-day tests seed easy
    cards explicitly, and a prior test's rows would otherwise leak in
    through the single-user ``select_daily_plan`` path.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-sessions-router-", suffix=".db")
    os.close(fd)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.test_session_factory = test_session_factory
    original_async_session = database_module.async_session
    database_module.async_session = test_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, test_session_factory

    app.dependency_overrides.pop(get_db, None)
    database_module.async_session = original_async_session
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")
    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _seed_user(session_factory) -> uuid.UUID:
    """Persist the single local user and return its id."""

    async with session_factory() as session:
        user = User(name="Bad-day Tester")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _seed_easy_problem(session_factory, user_id: uuid.UUID) -> uuid.UUID:
    """Seed one ``difficulty_layer == 1`` problem so the easy_only pool
    is non-empty when the happy-path test hits the endpoint."""

    async with session_factory() as session:
        course = Course(name="BadDay", description="x", user_id=user_id)
        session.add(course)
        await session.flush()

        problem = PracticeProblem(
            course_id=course.id,
            content_node_id=None,
            question_type="mc",
            question="Easy Q?",
            options={"choices": ["a", "b"]},
            correct_answer="a",
            order_index=0,
            difficulty_layer=1,
        )
        session.add(problem)
        await session.commit()
        await session.refresh(problem)
        return problem.id


# ── 1. Happy path — strategy=easy_only is accepted ─────────────────


@pytest.mark.asyncio
async def test_daily_plan_easy_only_returns_200(client_with_db) -> None:
    """Valid ``?strategy=easy_only`` round-trip returns 200 + DailyPlan
    shape. The pool can be empty under easy_only — we only assert the
    response schema, not cards."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    await _seed_easy_problem(factory, user_id)

    resp = await ac.get("/api/sessions/daily-plan?size=5&strategy=easy_only")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert "cards" in body
    assert "size" in body
    assert "reason" in body
    # The reason MUST be either None (happy path) or one of the two
    # allowed literals. No silent drift to a stray string.
    assert body["reason"] in (None, "nothing_due", "bad_day_empty")


# ── 2. struggle_first is NOT exposed on the public endpoint ────────


@pytest.mark.asyncio
async def test_daily_plan_struggle_first_rejected(client_with_db) -> None:
    """``strategy=struggle_first`` is an internal selector for the
    brutal drill; the public daily endpoint must 422 instead of silently
    returning a brutal batch."""

    ac, _factory = client_with_db

    resp = await ac.get("/api/sessions/daily-plan?size=5&strategy=struggle_first")
    assert resp.status_code == 422, resp.text


# ── 3. Unknown strategy → 422 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_plan_invalid_strategy_rejected(client_with_db) -> None:
    """Any value outside the ``DailyPlanStrategy`` literal → 422 from
    pydantic. Explicit to prove garbage input never reaches the service."""

    ac, _factory = client_with_db

    resp = await ac.get("/api/sessions/daily-plan?size=5&strategy=invalid")
    assert resp.status_code == 422, resp.text


# ── 4. Default strategy still works unchanged ──────────────────────


@pytest.mark.asyncio
async def test_daily_plan_default_strategy_unchanged(client_with_db) -> None:
    """No ``strategy`` query param → defaults to ``adhd_safe`` and the
    Phase 13 contract is untouched (regression guard for the router
    signature widening)."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    await _seed_easy_problem(factory, user_id)

    resp = await ac.get("/api/sessions/daily-plan?size=5")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "cards" in body
    assert body["reason"] in (None, "nothing_due")
