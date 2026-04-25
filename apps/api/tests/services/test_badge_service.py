"""Service tests for ``services.gamification.badge_service`` (Phase 16c
Bundle C — Subagent A).

Five groups:

1. **Catalog shape** — exact 10 entries; canonical key list locks the
   contract.
2. **Predicate behaviour** — each of the 10 predicates against a
   minimally-seeded SQLite DB.
3. **One-time award** — :func:`award_if_eligible` inserts on first
   eligible call, returns the existing row on the second (no
   duplicate).
4. **Predicate-False short-circuit** — :func:`award_if_eligible`
   returns ``None`` when the predicate is False.
5. **Bulk awarder** — :func:`award_all_eligible` awards multiple in
   one pass, repeated calls don't duplicate.

Harness mirrors ``tests/services/test_xp_service.py`` —
``sqlite+aiosqlite:///:memory:`` + ``StaticPool`` so the in-memory
``Base.metadata.create_all`` builds every table the service touches.
The new ``user_badges`` table is registered via the
``models.user_badge`` import at module top.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.freeze_token import FreezeToken  # noqa: F401 — register table
from models.learning_path import LearningPath, PathRoom
from models.user import User
from models.user_badge import UserBadge  # registers user_badges on Base
from models.xp_event import XpEvent
from services.gamification.badge_service import (
    CATALOG,
    award_all_eligible,
    award_if_eligible,
    catalog,
    evaluate_all,
    list_unlocked,
)


# Canonical key list per Bundle C spec A.2.
_EXPECTED_KEYS: tuple[str, ...] = (
    "first_card",
    "first_room_completed",
    "7_day_streak",
    "30_day_streak",
    "100_xp",
    "1000_xp",
    "python_fluent",
    "hacker_novice",
    "no_hint_hero",
    "comeback_kid",
)


# ── Fixtures ────────────────────────────────────────────────────────


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
    """One user, returned by id."""

    uid = uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=uid, name="Badge Tester"))
        await db.commit()
    return uid


# ── Seed helpers ────────────────────────────────────────────────────


async def _seed_xp_event(
    session_factory,
    *,
    user_id: uuid.UUID,
    amount: int,
    source: str,
    earned_at: datetime,
    source_id: uuid.UUID | None = None,
    metadata_json: dict | None = None,
) -> None:
    """Insert one XpEvent row."""

    async with session_factory() as db:
        db.add(
            XpEvent(
                user_id=user_id,
                amount=amount,
                source=source,
                source_id=source_id,
                earned_at=earned_at,
                metadata_json=metadata_json,
            )
        )
        await db.commit()


async def _seed_room_in_track(
    session_factory,
    *,
    track_id: str,
    slug: str = "py-room-1",
) -> uuid.UUID:
    """Seed a learning-path + path-room and return the room id."""

    path_id = uuid.uuid4()
    room_id = uuid.uuid4()
    async with session_factory() as db:
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
                slug=slug,
                title="Room",
                room_order=0,
            )
        )
        await db.commit()
    return room_id


# ── 1. Catalog shape ────────────────────────────────────────────────


def test_catalog_has_exactly_ten_entries():
    """Bundle C spec A.2: exactly 10 canonical badges."""

    assert len(CATALOG) == 10
    # Pure return — and same identity as the module-level tuple.
    assert catalog() is CATALOG


def test_catalog_keys_match_canonical_list():
    """Catalog keys are the canonical ones in spec A.2 — no drift."""

    actual = tuple(b.key for b in CATALOG)
    assert actual == _EXPECTED_KEYS


def test_catalog_entries_have_required_copy():
    """Every entry has non-empty title / description / hint and a callable."""

    for badge in CATALOG:
        assert badge.title.strip(), f"empty title for {badge.key}"
        assert badge.description.strip(), f"empty description for {badge.key}"
        assert badge.hint.strip(), f"empty hint for {badge.key}"
        assert callable(badge.predicate), f"non-callable predicate for {badge.key}"


# ── 2. Predicate behaviour ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_pred_first_card_true_after_practice_event(session_factory, user_id):
    """One ``practice_result`` xp event → first_card eligible."""

    async with session_factory() as db:
        # No events yet → False.
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["first_card"] is False

    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=2,
        source="practice_result",
        earned_at=datetime.now(timezone.utc),
        source_id=uuid.uuid4(),
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["first_card"] is True


@pytest.mark.asyncio
async def test_pred_first_room_true_after_room_complete_event(session_factory, user_id):
    """One ``room_complete`` xp event → first_room_completed eligible."""

    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=50,
        source="room_complete",
        earned_at=datetime.now(timezone.utc),
        source_id=uuid.uuid4(),
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["first_room_completed"] is True


@pytest.mark.asyncio
async def test_pred_xp_100_boundary(session_factory, user_id):
    """99 XP → False; 100 XP → True. Spec D boundary check."""

    # Seed 99 XP across distinct events so the dedup index doesn't trip.
    today = datetime.now(timezone.utc)
    for i in range(9):
        await _seed_xp_event(
            session_factory,
            user_id=user_id,
            amount=11,
            source="manual",
            earned_at=today - timedelta(days=i),
            source_id=None,
        )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["100_xp"] is False  # 99 XP

    # One more XP point pushes total to 100.
    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=1,
        source="manual",
        earned_at=today + timedelta(seconds=1),
        source_id=None,
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["100_xp"] is True


@pytest.mark.asyncio
async def test_pred_streak_7_at_boundary(session_factory, user_id):
    """6 consecutive XP days → False; 7 → True."""

    today_dt = datetime.now(timezone.utc)
    # 6 days first.
    for offset in range(6):
        await _seed_xp_event(
            session_factory,
            user_id=user_id,
            amount=10,
            source="practice_result",
            earned_at=today_dt - timedelta(days=offset),
            source_id=uuid.uuid4(),
        )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["7_day_streak"] is False
        assert eligibility["30_day_streak"] is False

    # Add the 7th day (one more behind the 6th).
    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=10,
        source="practice_result",
        earned_at=today_dt - timedelta(days=6),
        source_id=uuid.uuid4(),
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["7_day_streak"] is True
        assert eligibility["30_day_streak"] is False


@pytest.mark.asyncio
async def test_pred_python_and_hacker_track_completion(session_factory, user_id):
    """``track_id`` matching: python → python_fluent, hacking → hacker_novice."""

    py_room = await _seed_room_in_track(
        session_factory, track_id="python_fundamentals", slug="py-1"
    )
    hack_room = await _seed_room_in_track(
        session_factory, track_id="ethical_hacking", slug="hack-1"
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["python_fluent"] is False
        assert eligibility["hacker_novice"] is False

    # Complete a python room.
    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=30,
        source="room_complete",
        earned_at=datetime.now(timezone.utc),
        source_id=py_room,
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["python_fluent"] is True
        assert eligibility["hacker_novice"] is False

    # Complete a hacking room.
    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=60,
        source="hacking_room_complete",
        earned_at=datetime.now(timezone.utc) + timedelta(hours=1),
        source_id=hack_room,
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["python_fluent"] is True
        assert eligibility["hacker_novice"] is True


@pytest.mark.asyncio
async def test_pred_no_hint_reads_metadata(session_factory, user_id):
    """``no_hint_hero`` requires correctness>=1.0 AND hints_used==0 in metadata."""

    today = datetime.now(timezone.utc)
    # Event with hints_used > 0 — does NOT qualify.
    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=2,
        source="practice_result",
        earned_at=today,
        source_id=uuid.uuid4(),
        metadata_json={"hints_used": 1, "correctness": 1.0},
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["no_hint_hero"] is False

    # Event with hints_used == 0 AND correctness == 1.0 — qualifies.
    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=4,
        source="practice_result",
        earned_at=today + timedelta(hours=1),
        source_id=uuid.uuid4(),
        metadata_json={"hints_used": 0, "correctness": 1.0},
    )

    async with session_factory() as db:
        eligibility = await evaluate_all(db, user_id=user_id)
        assert eligibility["no_hint_hero"] is True


# ── 3. award_if_eligible — happy path + idempotence ─────────────────


@pytest.mark.asyncio
async def test_award_if_eligible_inserts_new_row(session_factory, user_id):
    """Predicate True + no prior row → fresh insert returned."""

    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=2,
        source="practice_result",
        earned_at=datetime.now(timezone.utc),
        source_id=uuid.uuid4(),
    )

    async with session_factory() as db:
        row = await award_if_eligible(db, user_id=user_id, badge_key="first_card")
        await db.commit()
        assert row is not None
        assert row.badge_key == "first_card"
        assert row.user_id == user_id


@pytest.mark.asyncio
async def test_award_if_eligible_idempotent_on_replay(session_factory, user_id):
    """Second award call returns the same row, doesn't duplicate."""

    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=2,
        source="practice_result",
        earned_at=datetime.now(timezone.utc),
        source_id=uuid.uuid4(),
    )

    async with session_factory() as db:
        first = await award_if_eligible(db, user_id=user_id, badge_key="first_card")
        await db.commit()
        assert first is not None
        first_id = first.id

    async with session_factory() as db:
        second = await award_if_eligible(db, user_id=user_id, badge_key="first_card")
        await db.commit()
        assert second is not None
        # Same row — no new insert.
        assert second.id == first_id

    async with session_factory() as db:
        rows = await list_unlocked(db, user_id=user_id)
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_award_if_eligible_returns_none_when_predicate_false(
    session_factory, user_id
):
    """No XP events at all → first_card predicate False → award returns None."""

    async with session_factory() as db:
        row = await award_if_eligible(db, user_id=user_id, badge_key="first_card")
        assert row is None
        rows = await list_unlocked(db, user_id=user_id)
        assert rows == []


@pytest.mark.asyncio
async def test_award_if_eligible_unknown_key_returns_none(session_factory, user_id):
    """Unknown badge key (not in CATALOG) returns None — no crash."""

    async with session_factory() as db:
        row = await award_if_eligible(db, user_id=user_id, badge_key="not-a-real-badge")
        assert row is None


# ── 4. award_all_eligible — bulk + non-duplicating ──────────────────


@pytest.mark.asyncio
async def test_award_all_eligible_awards_multiple(session_factory, user_id):
    """Seed enough state for several badges; one call awards them all."""

    # 100+ XP, first card, first room — three badges should fire.
    today = datetime.now(timezone.utc)
    # Card answers — practice_result events.
    for i in range(2):
        await _seed_xp_event(
            session_factory,
            user_id=user_id,
            amount=60,  # 2 × 60 = 120 XP — over the 100 threshold
            source="practice_result",
            earned_at=today - timedelta(days=i),
            source_id=uuid.uuid4(),
        )
    # Room completion.
    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=50,
        source="room_complete",
        earned_at=today,
        source_id=uuid.uuid4(),
    )

    async with session_factory() as db:
        new_rows = await award_all_eligible(db, user_id=user_id)
        await db.commit()

    awarded_keys = {r.badge_key for r in new_rows}
    # At least these three should fire.
    assert "first_card" in awarded_keys
    assert "first_room_completed" in awarded_keys
    assert "100_xp" in awarded_keys


@pytest.mark.asyncio
async def test_award_all_eligible_does_not_duplicate_on_replay(
    session_factory, user_id
):
    """Repeated ``award_all_eligible`` is idempotent — no extra rows."""

    await _seed_xp_event(
        session_factory,
        user_id=user_id,
        amount=2,
        source="practice_result",
        earned_at=datetime.now(timezone.utc),
        source_id=uuid.uuid4(),
    )

    async with session_factory() as db:
        first_pass = await award_all_eligible(db, user_id=user_id)
        await db.commit()
    assert len(first_pass) >= 1  # at least first_card

    async with session_factory() as db:
        second_pass = await award_all_eligible(db, user_id=user_id)
        await db.commit()
    # Second pass surfaces zero NEW rows — everything was already unlocked.
    assert second_pass == []

    async with session_factory() as db:
        all_rows = await list_unlocked(db, user_id=user_id)
        # Same count as the first pass — nothing duplicated.
        assert len(all_rows) == len(first_pass)


# ── 5. list_unlocked ordering ───────────────────────────────────────


@pytest.mark.asyncio
async def test_list_unlocked_returns_newest_first(session_factory, user_id):
    """Service spec: list_unlocked orders by ``unlocked_at DESC``."""

    older_id = uuid.uuid4()
    newer_id = uuid.uuid4()
    async with session_factory() as db:
        # Direct-insert two rows with explicit unlocked_at to test ordering.
        db.add(
            UserBadge(
                id=older_id,
                user_id=user_id,
                badge_key="first_card",
                unlocked_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
            )
        )
        db.add(
            UserBadge(
                id=newer_id,
                user_id=user_id,
                badge_key="100_xp",
                unlocked_at=datetime(2026, 4, 22, tzinfo=timezone.utc),
            )
        )
        await db.commit()

    async with session_factory() as db:
        rows = await list_unlocked(db, user_id=user_id)
    assert [r.id for r in rows] == [newer_id, older_id]
