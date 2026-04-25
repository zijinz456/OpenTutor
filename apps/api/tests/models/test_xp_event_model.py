"""ORM tests for the Phase 16c ``xp_events`` table — Subagent A scope.

Five thin tests covering the contract Subagent B will rely on:

1. Round-trip — every column survives SELECT.
2. CHECK constraint — ``amount = 300`` is rejected.
3. UNIQUE constraint — same ``(user_id, source_id, day)`` rejects the
   2nd insert.
4. Different days, same source — both succeed.
5. NULL ``source_id`` — manual grants are allowed and don't collide.

Harness: fresh in-memory SQLite per test using ``StaticPool`` so the
multiple connections inside one test all hit the same database. We
explicitly import ``models.xp_event`` (the new model is *not* yet
wired into ``models/__init__.py`` — that's Subagent B / integration
scope) so ``Base.metadata.create_all`` knows about the table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.user import User
from models.xp_event import XpEvent  # noqa: F401  — register with Base.metadata


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


@pytest_asyncio.fixture
async def user_id(session_factory):
    """Insert one ``User`` and return its id — xp_events.user_id is a FK."""
    uid = uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=uid, name="XP Tester"))
        await db.commit()
    return uid


# ── 1. Round-trip ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_xp_event_round_trip(session_factory, user_id):
    """Every persisted column reads back identical."""
    src_id = uuid.uuid4()
    earned = datetime(2026, 4, 25, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as db:
        evt = XpEvent(
            user_id=user_id,
            amount=42,
            source="practice_result",
            source_id=src_id,
            metadata_json={"difficulty_layer": 2, "hints_used": 0},
            earned_at=earned,
        )
        db.add(evt)
        await db.commit()
        evt_id = evt.id

    async with session_factory() as db:
        loaded = (
            await db.execute(sa.select(XpEvent).where(XpEvent.id == evt_id))
        ).scalar_one()
        assert loaded.user_id == user_id
        assert loaded.amount == 42
        assert loaded.source == "practice_result"
        assert loaded.source_id == src_id
        assert loaded.metadata_json == {"difficulty_layer": 2, "hints_used": 0}
        # Time round-trips, possibly with tz attached by the Base load
        # listener — compare as UTC.
        assert loaded.earned_at.astimezone(timezone.utc) == earned


# ── 2. CHECK constraint — amount range ───────────────────────────────


@pytest.mark.asyncio
async def test_check_constraint_rejects_oversize_amount(session_factory, user_id):
    """``amount = 300`` violates ``CHECK(amount BETWEEN -5 AND 200)``."""
    async with session_factory() as db:
        db.add(
            XpEvent(
                user_id=user_id,
                amount=300,
                source="manual",
                source_id=None,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


# ── 3. UNIQUE constraint — anti-spam same-day same-source ────────────


@pytest.mark.asyncio
async def test_unique_constraint_same_day_same_source(session_factory, user_id):
    """Two events with same (user_id, source_id, day) — 2nd fails."""
    src_id = uuid.uuid4()
    day = datetime(2026, 4, 25, 9, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as db:
        db.add(
            XpEvent(
                user_id=user_id,
                amount=2,
                source="practice_result",
                source_id=src_id,
                earned_at=day,
            )
        )
        await db.commit()

    # Second insert later the same day — different ``earned_at`` but
    # the functional unique index is on ``date(earned_at)`` so both
    # land on the same bucket.
    async with session_factory() as db:
        db.add(
            XpEvent(
                user_id=user_id,
                amount=2,
                source="practice_result",
                source_id=src_id,
                earned_at=day + timedelta(hours=8),
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


# ── 4. Different days, same source — both succeed ────────────────────


@pytest.mark.asyncio
async def test_different_days_same_source_both_insert(session_factory, user_id):
    """A user can earn XP for the same problem across two different days."""
    src_id = uuid.uuid4()
    async with session_factory() as db:
        db.add(
            XpEvent(
                user_id=user_id,
                amount=2,
                source="practice_result",
                source_id=src_id,
                earned_at=datetime(2026, 4, 25, 9, 0, 0, tzinfo=timezone.utc),
            )
        )
        db.add(
            XpEvent(
                user_id=user_id,
                amount=2,
                source="practice_result",
                source_id=src_id,
                earned_at=datetime(2026, 4, 26, 9, 0, 0, tzinfo=timezone.utc),
            )
        )
        await db.commit()

    async with session_factory() as db:
        count = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(XpEvent)
                .where(XpEvent.source_id == src_id)
            )
        ).scalar_one()
        assert count == 2


# ── 5. NULL source_id — manual grants allowed multiple times same day ─


@pytest.mark.asyncio
async def test_nullable_source_id_allows_multiple_manual_grants(
    session_factory, user_id
):
    """Manual XP rows have NULL ``source_id``; the partial unique index
    excludes them so two manual grants on the same day both insert."""
    earned = datetime(2026, 4, 25, 9, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as db:
        db.add(
            XpEvent(
                user_id=user_id,
                amount=5,
                source="manual",
                source_id=None,
                earned_at=earned,
            )
        )
        db.add(
            XpEvent(
                user_id=user_id,
                amount=10,
                source="manual",
                source_id=None,
                earned_at=earned + timedelta(hours=2),
            )
        )
        await db.commit()

    async with session_factory() as db:
        count = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(XpEvent)
                .where(XpEvent.source == "manual")
            )
        ).scalar_one()
        assert count == 2
