"""Router tests for ``GET /api/gamification/badges`` (Phase 16c Bundle C).

Acceptance criteria from `claude_task_phase16c_bundle_c_badges.md` Part D:

1. Empty state — new account → ``unlocked == []`` and ``locked`` length
   equals the catalog size (10).
2. Mixed state — pre-seed two ``user_badges`` rows → ``unlocked``
   carries them with ``unlocked_at``; ``locked`` covers the remaining 8
   with ``hint`` populated.
3. Locked rows always carry ``hint`` text (so the locked-state UI can
   tell users *how* to earn them).
4. Unlocked rows carry their ``unlocked_at`` timestamps from the DB row.

Harness mirrors :mod:`tests.routers.test_gamification` — temp SQLite,
``app.dependency_overrides[get_db]``, mount the router on the shared
app once. The shared app already mounts gamification via the prior
test module; we tolerate the prior mount and reuse it.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from models.user import User
from models.user_badge import UserBadge  # registers user_badges on Base
from routers.gamification import router as gamification_router
from services.gamification.badge_service import CATALOG


# ── App-level mount (idempotent) ────────────────────────────────────

_MOUNT_PATH = "/api/gamification"


def _ensure_mounted() -> None:
    for route in app.routes:
        if getattr(route, "path", "").startswith(_MOUNT_PATH):
            return
    app.include_router(gamification_router)


_ensure_mounted()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client_with_db():
    fd, db_path = tempfile.mkstemp(prefix="opentutor-badges-router-", suffix=".db")
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
        await conn.execute(text("PRAGMA writable_schema = 1"))
        await conn.execute(
            text(
                "UPDATE sqlite_master SET sql = replace(sql, 'NOT NULL', '') "
                "WHERE name = 'freeze_tokens'"
            )
        )
        await conn.execute(text("PRAGMA writable_schema = 0"))

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
    async with session_factory() as session:
        user = User(name="Owner")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _seed_unlocks(
    session_factory, *, user_id: uuid.UUID, keys: list[str]
) -> None:
    """Insert one ``user_badges`` row per key, all timestamped now-UTC."""

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        for key in keys:
            session.add(UserBadge(user_id=user_id, badge_key=key, unlocked_at=now))
        await session.commit()


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_badges_empty_account_returns_full_locked_catalog(client_with_db):
    """New account → no unlocked rows; every catalog entry locked."""

    ac, factory = client_with_db
    await _seed_user(factory)

    resp = await ac.get("/api/gamification/badges")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unlocked"] == []
    assert len(body["locked"]) == len(CATALOG)
    locked_keys = {row["key"] for row in body["locked"]}
    assert locked_keys == {b.key for b in CATALOG}


@pytest.mark.asyncio
async def test_badges_mixed_unlocked_and_locked(client_with_db):
    """Two unlocks → unlocked has 2 rows with timestamps; locked covers the rest."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    seeded = ["first_card", "100_xp"]
    await _seed_unlocks(factory, user_id=user_id, keys=seeded)

    resp = await ac.get("/api/gamification/badges")
    assert resp.status_code == 200
    body = resp.json()

    unlocked_keys = {row["key"] for row in body["unlocked"]}
    assert unlocked_keys == set(seeded)
    for row in body["unlocked"]:
        assert row["unlocked"] is True
        assert row["unlocked_at"] is not None

    locked_keys = {row["key"] for row in body["locked"]}
    assert locked_keys == {b.key for b in CATALOG} - set(seeded)
    assert len(body["locked"]) == len(CATALOG) - len(seeded)


@pytest.mark.asyncio
async def test_locked_badges_carry_hint_copy(client_with_db):
    """Every locked entry must include non-empty ``hint`` text for the UI."""

    ac, factory = client_with_db
    await _seed_user(factory)

    resp = await ac.get("/api/gamification/badges")
    assert resp.status_code == 200
    body = resp.json()
    assert all(row["hint"] for row in body["locked"])
    assert all(row["unlocked"] is False for row in body["locked"])
    assert all(row["unlocked_at"] is None for row in body["locked"])


@pytest.mark.asyncio
async def test_unlocked_badges_carry_unlocked_at(client_with_db):
    """Unlocked rows must surface the timestamp from the DB row."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    await _seed_unlocks(factory, user_id=user_id, keys=["7_day_streak"])

    resp = await ac.get("/api/gamification/badges")
    body = resp.json()
    [unlocked_row] = body["unlocked"]
    assert unlocked_row["key"] == "7_day_streak"
    assert unlocked_row["unlocked"] is True
    # ISO-8601 with timezone marker (Z or +00:00)
    assert "T" in unlocked_row["unlocked_at"]
