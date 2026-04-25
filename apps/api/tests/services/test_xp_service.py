"""Service tests for ``services.xp_service`` — Phase 16c Subagent A.

Three groups:

1. **Pure-fn tier maths** (``tier_name`` / ``level_progress_pct``) —
   table-driven, no DB.
2. **Pure-fn ``compute_xp``** — covers every branch of the formula
   (Story 2 #2): card correct/wrong/half, with/without each bonus,
   room/hacking-room with cap, manual.
3. **DB awarders** — fresh in-memory SQLite, asserts the unique-index
   dedup, the next-UTC-day case, and the helpers
   ``get_user_xp_total`` / ``get_xp_events_in_range``.

Harness mirrors ``tests/services/test_path_room_factory.py`` —
``sqlite+aiosqlite:///:memory:`` + ``StaticPool`` + import the new
model so the in-memory ``Base.metadata.create_all`` knows about it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from database import Base
from models.user import User
from models.xp_event import XpEvent  # noqa: F401  — register table
from services import xp_service
from services.xp_service import (
    EventType,
    award_card_xp,
    award_room_xp,
    compute_xp,
    get_user_xp_total,
    get_xp_events_in_range,
    level_progress_pct,
    tier_name,
)


# ── Fixtures ─────────────────────────────────────────────────────────


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
        db.add(User(id=uid, name="XP Tester"))
        await db.commit()
    return uid


# ── 1. tier_name ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "xp_total,expected",
    [
        (0, "Bronze I"),
        (165, "Bronze I"),
        (166, "Bronze II"),
        (333, "Bronze III"),
        (499, "Bronze III"),
        (500, "Silver I"),
        (600, "Silver I"),
        (1000, "Silver II"),
        (2000, "Gold I"),
        (5000, "Platinum I"),
        (10000, "Diamond I"),
        (50000, "Diamond I"),
    ],
)
def test_tier_name_boundaries(xp_total: int, expected: str):
    """Hard-coded boundary table from the spec — locks the contract."""
    assert tier_name(xp_total) == expected


# ── 2. level_progress_pct ────────────────────────────────────────────


@pytest.mark.parametrize(
    "xp_total,expected_pct",
    [
        (0, 0),
        (250, 50),
        (499, 99),
        (500, 0),  # Crossed into Silver — back to 0%.
        (1500, 66),  # 1000/1500 inside Silver (band 500..1999).
        (10000, 0),  # Diamond is open-ended; pct stays 0.
        (99999, 0),
    ],
)
def test_level_progress_pct(xp_total: int, expected_pct: int):
    assert level_progress_pct(xp_total) == expected_pct


# ── 3. compute_xp formula table ──────────────────────────────────────


def test_compute_xp_card_correct_with_bonuses():
    """layer=2, no hint, fast (5s) → 2 (base) + 1 (no-hint) + 1 (fast) = 4."""
    assert (
        compute_xp(
            event_type="card",
            difficulty_layer=2,
            correctness=1.0,
            hints_used=0,
            answer_time_ms=5_000,
        )
        == 4
    )


def test_compute_xp_card_correct_no_bonuses():
    """layer=1 → no fast bonus (gate is layer >= 2). Hint used → no no-hint."""
    assert (
        compute_xp(
            event_type="card",
            difficulty_layer=1,
            correctness=1.0,
            hints_used=1,
            answer_time_ms=5_000,
        )
        == 1
    )


def test_compute_xp_card_correct_layer3_fast():
    """layer=3, no hint, fast → 3 + 1 + 1 = 5."""
    assert (
        compute_xp(
            event_type="card",
            difficulty_layer=3,
            correctness=1.0,
            hints_used=0,
            answer_time_ms=2_000,
        )
        == 5
    )


def test_compute_xp_card_wrong_consolation():
    """correctness=0.0 → +1 (Story 2 #2 — kill the don't-try pattern)."""
    assert (
        compute_xp(
            event_type="card",
            difficulty_layer=3,  # difficulty doesn't matter for wrong
            correctness=0.0,
            hints_used=0,
        )
        == 1
    )


def test_compute_xp_card_half_credit_no_bonuses():
    """correctness=0.5, layer=3 → round(1.5) = 2; no no-hint/fast bonuses."""
    assert (
        compute_xp(
            event_type="card",
            difficulty_layer=3,
            correctness=0.5,
            hints_used=0,
            answer_time_ms=2_000,
        )
        == 2
    )


def test_compute_xp_room_complete_under_cap():
    """7 tasks × 10 = 70, under +100 cap."""
    assert compute_xp(event_type="room_complete", task_count=7) == 70


def test_compute_xp_room_complete_capped():
    """15 tasks × 10 = 150 → capped at +100."""
    assert compute_xp(event_type="room_complete", task_count=15) == 100


def test_compute_xp_hacking_room_under_cap():
    """5 tasks × 20 = 100, under +200 cap."""
    assert compute_xp(event_type="hacking_room_complete", task_count=5) == 100


def test_compute_xp_hacking_room_capped():
    """15 tasks × 20 = 300 → capped at +200."""
    assert compute_xp(event_type="hacking_room_complete", task_count=15) == 200


def test_compute_xp_manual_clamped():
    """Manual grant respects the [-5, 200] CHECK clamp."""
    assert compute_xp(event_type="manual", manual_amount=42) == 42
    assert compute_xp(event_type="manual", manual_amount=999) == 200
    assert compute_xp(event_type="manual", manual_amount=-100) == -5


def test_compute_xp_unknown_event_type_raises():
    """Unknown event types fail loud — no silent zero-XP grants.

    The ``Literal`` type-hint catches this at static-check time; the
    runtime ``ValueError`` is the belt-and-braces guard for callers
    using untyped (e.g. dict-driven) dispatch. We feed the bad value
    through a typed-erased ``cast`` so this test compiles under ty.
    """
    from typing import cast

    bad: EventType = cast("EventType", "bogus")
    with pytest.raises(ValueError):
        compute_xp(event_type=bad)


# ── 4. award_card_xp happy path ──────────────────────────────────────


@pytest.mark.asyncio
async def test_award_card_xp_inserts_event(session_factory, user_id):
    """Happy path: row inserted, amount matches the formula output."""
    pid = uuid.uuid4()
    async with session_factory() as db:
        evt = await award_card_xp(
            db,
            user_id=user_id,
            problem_id=pid,
            difficulty_layer=2,
            correctness=1.0,
            hints_used=0,
            answer_time_ms=5_000,
        )
        await db.commit()
        assert evt is not None
        assert evt.amount == 4  # 2 + 1 (no-hint) + 1 (fast)
        assert evt.source == "practice_result"
        assert evt.source_id == pid

    async with session_factory() as db:
        rows = (
            (await db.execute(sa.select(XpEvent).where(XpEvent.source_id == pid)))
            .scalars()
            .all()
        )
        assert len(rows) == 1


# ── 5. award_card_xp dedup same UTC day ──────────────────────────────


@pytest.mark.asyncio
async def test_award_card_xp_dedups_same_day(session_factory, user_id):
    """Second award for the same problem same UTC day → ``None``."""
    pid = uuid.uuid4()
    async with session_factory() as db:
        first = await award_card_xp(
            db,
            user_id=user_id,
            problem_id=pid,
            difficulty_layer=1,
            correctness=1.0,
        )
        await db.commit()
        assert first is not None

        second = await award_card_xp(
            db,
            user_id=user_id,
            problem_id=pid,
            difficulty_layer=1,
            correctness=1.0,
        )
        # Dedup: returns None, parent tx still healthy enough to commit.
        assert second is None
        await db.commit()

    async with session_factory() as db:
        count = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(XpEvent)
                .where(XpEvent.source_id == pid)
            )
        ).scalar_one()
        assert count == 1


# ── 6. award_card_xp succeeds across day boundary ────────────────────


@pytest.mark.asyncio
async def test_award_card_xp_next_day_succeeds(session_factory, user_id, monkeypatch):
    """Monkey-patch ``datetime.now`` inside xp_service to step a day
    forward; the second award lands in a fresh day-bucket and is
    allowed by the unique index."""
    pid = uuid.uuid4()
    day_one = datetime(2026, 4, 25, 9, 0, 0, tzinfo=timezone.utc)
    day_two = datetime(2026, 4, 26, 9, 0, 0, tzinfo=timezone.utc)

    class _FakeDatetime:
        _now = day_one

        @classmethod
        def now(cls, tz=None):  # noqa: ARG003 — match real signature
            return cls._now

    monkeypatch.setattr(xp_service, "datetime", _FakeDatetime)

    async with session_factory() as db:
        first = await award_card_xp(
            db,
            user_id=user_id,
            problem_id=pid,
            difficulty_layer=1,
            correctness=1.0,
        )
        await db.commit()
        assert first is not None

        # Step forward one day — same problem, fresh dedup bucket.
        _FakeDatetime._now = day_two
        second = await award_card_xp(
            db,
            user_id=user_id,
            problem_id=pid,
            difficulty_layer=1,
            correctness=1.0,
        )
        await db.commit()
        assert second is not None

    async with session_factory() as db:
        count = (
            await db.execute(
                sa.select(sa.func.count())
                .select_from(XpEvent)
                .where(XpEvent.source_id == pid)
            )
        ).scalar_one()
        assert count == 2


# ── 7. award_room_xp standard vs hacking ─────────────────────────────


@pytest.mark.asyncio
async def test_award_room_xp_standard_vs_hacking(session_factory, user_id):
    """Hacking rooms award the ×2 multiplier and the higher cap."""
    standard_room_id = uuid.uuid4()
    hacking_room_id = uuid.uuid4()
    async with session_factory() as db:
        std = await award_room_xp(
            db,
            user_id=user_id,
            room_id=standard_room_id,
            task_count=5,
            is_hacking=False,
        )
        hack = await award_room_xp(
            db,
            user_id=user_id,
            room_id=hacking_room_id,
            task_count=5,
            is_hacking=True,
        )
        await db.commit()

    assert std is not None
    assert hack is not None
    assert std.amount == 50  # 5 × 10
    assert hack.amount == 100  # 5 × 20
    assert std.source == "room_complete"
    assert hack.source == "hacking_room_complete"


# ── 8. get_user_xp_total ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_user_xp_total_sums_and_zero_default(session_factory, user_id):
    """Sum across multiple events; new user reads as 0."""
    other = uuid.uuid4()
    async with session_factory() as db:
        db.add(User(id=other, name="Other"))
        await db.commit()

    async with session_factory() as db:
        # Three separate problems → three different source_ids → no
        # dedup interference.
        for amount in (5, 10, 7):
            db.add(
                XpEvent(
                    user_id=user_id,
                    amount=amount,
                    source="practice_result",
                    source_id=uuid.uuid4(),
                )
            )
        await db.commit()

    async with session_factory() as db:
        assert await get_user_xp_total(db, user_id=user_id) == 22
        assert await get_user_xp_total(db, user_id=other) == 0


# ── 9. get_xp_events_in_range — boundary inclusive ───────────────────


@pytest.mark.asyncio
async def test_get_xp_events_in_range_inclusive(session_factory, user_id):
    """Events with ``earned_at == start`` or ``== end`` are included."""
    start = datetime(2026, 4, 20, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 4, 22, 23, 59, 59, tzinfo=timezone.utc)

    async with session_factory() as db:
        db.add_all(
            [
                XpEvent(
                    user_id=user_id,
                    amount=1,
                    source="manual",
                    source_id=None,
                    earned_at=start - timedelta(seconds=1),  # before
                ),
                XpEvent(
                    user_id=user_id,
                    amount=2,
                    source="manual",
                    source_id=None,
                    earned_at=start,  # inclusive low
                ),
                XpEvent(
                    user_id=user_id,
                    amount=3,
                    source="manual",
                    source_id=None,
                    earned_at=start + timedelta(days=1),  # middle
                ),
                XpEvent(
                    user_id=user_id,
                    amount=4,
                    source="manual",
                    source_id=None,
                    earned_at=end,  # inclusive high
                ),
                XpEvent(
                    user_id=user_id,
                    amount=5,
                    source="manual",
                    source_id=None,
                    earned_at=end + timedelta(seconds=1),  # after
                ),
            ]
        )
        await db.commit()

    async with session_factory() as db:
        rows = await get_xp_events_in_range(
            db, user_id=user_id, start_utc=start, end_utc=end
        )

    amounts = [r.amount for r in rows]
    assert amounts == [2, 3, 4]  # ordered oldest-first, boundaries kept
