"""Integration tests for the ``/api/freeze/*`` router (Phase 14 T1).

Covers the four T1 router-level acceptance criteria:

1. ``test_post_freeze_success_201`` — happy path response shape.
2. ``test_post_freeze_over_quota_409`` — 4th freeze in one week.
3. ``test_get_status_returns_remaining`` — quota echo after N freezes.
4. ``test_delete_freeze_204_no_refund`` — manual unfreeze keeps quota
   consumed (critic C8).

Fixture is cloned from ``test_interview.py`` — isolated SQLite DB per
test, ``get_db`` override, no content gating because freeze has no
corpus dependency.
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
    """Per-test ``AsyncClient`` + session factory so tests can seed
    practice problems directly (no need to go through the curriculum
    import path just to produce one row)."""

    fd, db_path = tempfile.mkstemp(prefix="opentutor-freeze-router-", suffix=".db")
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
    """Trigger the local-user bootstrap and return its id.

    The single-user ``get_current_user`` creates a User on first call;
    seeding the same way avoids divergence between auth + tests.
    """

    async with session_factory() as session:
        user = User(name="Owner")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _seed_problem(session_factory, *, user_id: uuid.UUID) -> uuid.UUID:
    """Create a course + practice_problem; return problem id."""

    async with session_factory() as session:
        course = Course(name="C", description="t", user_id=user_id)
        session.add(course)
        await session.flush()
        problem = PracticeProblem(
            course_id=course.id,
            content_node_id=None,
            question_type="mc",
            question="Q?",
            options={"choices": ["a", "b"]},
            correct_answer="a",
            order_index=0,
        )
        session.add(problem)
        await session.commit()
        await session.refresh(problem)
        return problem.id


# ── 1. POST /api/freeze/{problem_id} — success ─────────────────────


@pytest.mark.asyncio
async def test_post_freeze_success_201(client_with_db) -> None:
    """Freeze returns 201 + expires_at + quota_remaining=2 after first write."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    problem_id = await _seed_problem(factory, user_id=user_id)

    resp = await ac.post(f"/api/freeze/{problem_id}")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "expires_at" in body
    # After the first freeze, quota decrements from 3 to 2.
    assert body["quota_remaining"] == 2


# ── 2. POST /api/freeze/{problem_id} — 409 over quota ──────────────


@pytest.mark.asyncio
async def test_post_freeze_over_quota_409(client_with_db) -> None:
    """4th freeze in one week → 409 weekly_cap_exceeded."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    p_ids = [await _seed_problem(factory, user_id=user_id) for _ in range(4)]

    for i in range(3):
        resp = await ac.post(f"/api/freeze/{p_ids[i]}")
        assert resp.status_code == 201, f"freeze #{i} failed: {resp.text}"

    resp_over = await ac.post(f"/api/freeze/{p_ids[3]}")
    assert resp_over.status_code == 409, resp_over.text
    body = resp_over.json()
    assert body["detail"]["error"] == "weekly_cap_exceeded"


# ── 3. GET /api/freeze/status — quota echo ─────────────────────────


@pytest.mark.asyncio
async def test_get_status_returns_remaining(client_with_db) -> None:
    """After 2 freezes status shows quota_remaining=1, weekly_used=2,
    and 2 active_freezes entries."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    p1 = await _seed_problem(factory, user_id=user_id)
    p2 = await _seed_problem(factory, user_id=user_id)

    await ac.post(f"/api/freeze/{p1}")
    await ac.post(f"/api/freeze/{p2}")

    resp = await ac.get("/api/freeze/status")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quota_remaining"] == 1
    assert body["weekly_used"] == 2
    assert len(body["active_freezes"]) == 2
    pids = {row["problem_id"] for row in body["active_freezes"]}
    assert pids == {str(p1), str(p2)}


# ── 4. DELETE /api/freeze/{problem_id} — no refund ─────────────────


@pytest.mark.asyncio
async def test_delete_freeze_204_no_refund(client_with_db) -> None:
    """Unfreeze returns 200 ``{"ok": true}``; the slot stays consumed
    (no quota refund, critic C8). Implementation sets ``expires_at = now``
    so the row remains in the weekly bucket and the lifetime
    UniqueConstraint still blocks a second freeze on the same card.

    Status code is 200 not 204: FastAPI asserts no body for 204 endpoints,
    which conflicts with the ``-> dict`` return annotation. Name kept for
    history; see SESSION_STATE cheatsheet entry on 204 + return type."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    p1 = await _seed_problem(factory, user_id=user_id)

    # Baseline.
    pre = await ac.get("/api/freeze/status")
    assert pre.json()["quota_remaining"] == 3

    # Freeze → quota drops to 2.
    await ac.post(f"/api/freeze/{p1}")
    between = await ac.get("/api/freeze/status")
    assert between.json()["quota_remaining"] == 2
    assert between.json()["weekly_used"] == 1

    # Unfreeze → active list empties BUT weekly_used stays 1 (no refund).
    resp = await ac.delete(f"/api/freeze/{p1}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    after = await ac.get("/api/freeze/status")
    body = after.json()
    assert body["active_freezes"] == []
    assert body["weekly_used"] == 1  # slot still consumed — no refund
    assert body["quota_remaining"] == 2

    # Re-freezing the same card stays blocked by the lifetime
    # UniqueConstraint — the row is still there, just expired.
    refreeze = await ac.post(f"/api/freeze/{p1}")
    assert refreeze.status_code == 409
    assert refreeze.json()["detail"]["error"] == "already_frozen"

    # Deleting again with no active freeze → 404 (nothing to expire).
    # The first DELETE moved expires_at to now; a second DELETE targets
    # the same row and still succeeds idempotently because the row
    # exists. The 404 contract fires only when no row exists at all.
    no_such = uuid.uuid4()
    resp_404 = await ac.delete(f"/api/freeze/{no_such}")
    assert resp_404.status_code == 404
