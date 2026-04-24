"""Integration tests for ``GET /api/sessions/welcome-back`` (Phase 14 T4).

Covers the T4 router-level acceptance criteria:

1. ``test_welcome_back_new_user_200_nulls`` — brand-new account returns
   ``{gap_days: null, last_practice_at: null, top_mastered_concepts: [],
   overdue_count: 0}``.
2. ``test_welcome_back_returning_user_gap_three`` — a user whose last
   answer was 3 UTC days ago gets ``gap_days == 3`` plus the populated
   ``last_practice_at`` / ``top_mastered_concepts`` fields.

Fixture cloned from ``test_freeze.py`` — isolated SQLite DB per test,
``get_db`` override, ``ASGITransport`` in-process client. Single-user
deployment mode is the default (``AUTH_ENABLED=false``), so
unauthenticated 401 is unreachable here — the auth dependency
auto-materialises the single local user, which matches how the sister
``test_freeze.py`` suite exercises the same endpoint family.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from libs.datetime_utils import utcnow
from main import app
from models.content import CourseContentTree
from models.course import Course
from models.practice import PracticeProblem, PracticeResult
from models.user import User


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client_with_db():
    """Per-test ``AsyncClient`` + session factory so tests can seed rows
    directly before exercising the endpoint."""

    fd, db_path = tempfile.mkstemp(prefix="opentutor-welcome-router-", suffix=".db")
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
    """Create the single local user and return its id.

    The ``get_current_user`` dependency auto-creates one if missing; we
    seed explicitly so the rows we attach to it use a known user_id.
    """

    async with session_factory() as session:
        user = User(name="Owner")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


# ── 1. New user → nulls and zero overdue ───────────────────────────


@pytest.mark.asyncio
async def test_welcome_back_new_user_200_nulls(client_with_db) -> None:
    """A fresh account with no history gets the zero payload."""

    ac, _factory = client_with_db

    resp = await ac.get("/api/sessions/welcome-back")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["gap_days"] is None
    assert body["last_practice_at"] is None
    assert body["top_mastered_concepts"] == []
    assert body["overdue_count"] == 0


# ── 2. Returning user (gap=3 days, one mastered concept) ───────────


@pytest.mark.asyncio
async def test_welcome_back_returning_user_gap_three(client_with_db) -> None:
    """A user whose last answer was 3 UTC days ago sees gap_days=3, a
    populated ``last_practice_at``, and their most recent mastered
    content-node title in ``top_mastered_concepts``.
    """

    ac, factory = client_with_db
    user_id = await _seed_user(factory)

    three_days_ago = utcnow() - timedelta(days=3)

    async with factory() as session:
        course = Course(name="WB", description="x", user_id=user_id)
        session.add(course)
        await session.flush()

        node = CourseContentTree(
            course_id=course.id,
            title="Pointers",
            level=1,
            order_index=0,
            source_type="manual",
        )
        session.add(node)
        await session.flush()

        problem = PracticeProblem(
            course_id=course.id,
            content_node_id=node.id,
            question_type="mc",
            question="Q?",
            options={"choices": ["a", "b"]},
            correct_answer="a",
            order_index=0,
        )
        session.add(problem)
        await session.flush()

        session.add(
            PracticeResult(
                problem_id=problem.id,
                user_id=user_id,
                user_answer="a",
                is_correct=True,
                answered_at=three_days_ago,
            )
        )
        await session.commit()

    resp = await ac.get("/api/sessions/welcome-back")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["gap_days"] == 3
    assert body["last_practice_at"] is not None
    assert body["top_mastered_concepts"] == ["Pointers"]
    # No LearningProgress rows seeded → overdue stays at zero.
    assert body["overdue_count"] == 0
