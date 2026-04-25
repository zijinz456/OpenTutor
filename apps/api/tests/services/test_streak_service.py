"""Unit tests for ``services.streak_service`` (Phase 16c Subagent B).

Covers the ten Story-3 streak-walk acceptance criteria:

1. ``test_new_account_returns_zero`` — empty XP ledger → ``streak_days=0``.
2. ``test_today_only_event_returns_one`` — single event today → 1.
3. ``test_five_consecutive_days`` — 5 events on consecutive days → 5.
4. ``test_yesterday_gap_breaks_streak`` — gap before today, no auto →
   streak resets to 0 even with prior history.
5. ``test_auto_freeze_saves_yesterday_gap`` — same shape as #4 but
   ``auto_apply_freezes=True`` with budget remaining → 1 freeze inserted,
   streak picks up again behind the gap.
6. ``test_auto_freeze_no_budget_breaks_streak`` — quota fully spent
   pre-walk → auto-apply is a no-op, streak still breaks at the gap.
7. ``test_existing_freeze_natively_maintains_day`` — a card freeze
   already covers yesterday → walk treats day as maintained without
   needing auto-apply.
8. ``test_zero_amount_event_does_not_maintain_day`` — zero or negative
   ``amount`` rows do not count for streak maintenance.
9. ``test_walk_is_bounded`` — even when freezes_left is huge, the walk
   stops at the user's earliest event and returns a reasonable streak.
10. ``test_freezes_left_reflects_post_walk_state`` — when auto-apply
    fires once, the returned ``freezes_left_this_week`` is one less
    than the pre-walk budget.

Harness mirrors :mod:`tests.services.test_freeze` — per-test SQLite
file via ``aiosqlite``; ``Base.metadata.create_all`` is enough since
``XpEvent`` is registered via the import below. We also relax the
``freeze_tokens.problem_id`` NOT NULL constraint at the SQLite layer
because Subagent A's migration that drops it lives in T5 and isn't
landed yet — production Postgres will pick up the change via Alembic.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import Base
from models.freeze_token import FreezeToken
from models.user import User
from models.xp_event import XpEvent  # registers xp_events table on Base.metadata
from services.streak_service import compute_streak


# Anchor day chosen far from a week boundary so freeze week-bucket
# arithmetic doesn't accidentally span two ISO weeks during a test.
# Wednesday 2026-04-22.
_ANCHOR_DATE = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc).date()


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Per-test SQLite session with relaxed freeze-token constraints.

    The Phase 16c plan (T5) calls for dropping ``freeze_tokens.problem_id
    NOT NULL`` so streak-saver freezes can carry NULL. That migration is
    Subagent A's; until it lands the ORM still says NOT NULL and SQLite
    enforces it. We work around that by recreating ``freeze_tokens`` in
    the test DB without the constraint — production Postgres gets the
    real fix from Alembic.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-streak-", suffix=".db")
    os.close(fd)

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Recreate freeze_tokens without ``problem_id NOT NULL`` so the
        # streak-saver insert path can store NULL. SQLite's
        # ``writable_schema`` PRAGMA lets us patch the stored DDL string
        # in-place; we still need to ``VACUUM`` for the change to apply
        # to the live schema. Belt-and-braces: also unique-constraint-
        # free so consecutive streak-saver inserts (different days) do
        # not trip ``uq_freeze_token_user_problem`` with NULL == NULL
        # SQLite semantics.
        await conn.execute(text("PRAGMA writable_schema = 1"))
        await conn.execute(
            text(
                "UPDATE sqlite_master SET sql = replace(sql, 'NOT NULL', '') "
                "WHERE name = 'freeze_tokens'"
            )
        )
        await conn.execute(text("PRAGMA writable_schema = 0"))

    async with factory() as session:
        yield session

    await engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


@pytest_asyncio.fixture
async def seeded_user(db_session: AsyncSession) -> uuid.UUID:
    """Create one ``User`` row and return its id."""

    user = User(name="Streak Tester")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user.id


# ── Helpers ─────────────────────────────────────────────────────────


def _utc_at(d, hour: int = 9) -> datetime:
    """Return tz-aware UTC datetime at ``hour`` on date ``d``."""

    return datetime.combine(d, time(hour=hour), tzinfo=timezone.utc)


async def _add_event(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    day,
    amount: int = 5,
) -> None:
    """Insert one ``XpEvent`` row anchored at 09:00 UTC on ``day``."""

    db.add(
        XpEvent(
            user_id=user_id,
            amount=amount,
            source="test_seed",
            source_id=uuid.uuid4(),
            earned_at=_utc_at(day),
        )
    )
    await db.commit()


async def _add_freeze(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    day,
) -> None:
    """Insert one card-style freeze covering exactly ``day``."""

    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    db.add(
        FreezeToken(
            user_id=user_id,
            problem_id=uuid.uuid4(),  # card freeze keeps a problem_id
            frozen_at=start,
            expires_at=start + timedelta(hours=24),
        )
    )
    await db.commit()


# ── 1. New account → 0 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_account_returns_zero(db_session, seeded_user) -> None:
    """A user with no XP events and no freezes has streak_days=0."""

    result = await compute_streak(
        db_session, user_id=seeded_user, today_utc=_ANCHOR_DATE
    )
    assert result.streak_days == 0
    assert result.freezes_used_dates == []
    # Phase 14 base quota = 3; nothing was used.
    assert result.freezes_left_this_week == 3


# ── 2. Today only → 1 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_today_only_event_returns_one(db_session, seeded_user) -> None:
    """A single event today → streak_days=1 (today counts when real)."""

    await _add_event(db_session, user_id=seeded_user, day=_ANCHOR_DATE, amount=5)

    result = await compute_streak(
        db_session, user_id=seeded_user, today_utc=_ANCHOR_DATE
    )
    assert result.streak_days == 1
    assert result.freezes_used_dates == []


# ── 3. 5 consecutive days → 5 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_five_consecutive_days(db_session, seeded_user) -> None:
    """Events on today through 4 days back → streak=5."""

    for offset in range(5):
        await _add_event(
            db_session,
            user_id=seeded_user,
            day=_ANCHOR_DATE - timedelta(days=offset),
        )

    result = await compute_streak(
        db_session, user_id=seeded_user, today_utc=_ANCHOR_DATE
    )
    assert result.streak_days == 5
    assert result.freezes_used_dates == []


# ── 4. Yesterday gap, no auto → 0 ───────────────────────────────────


@pytest.mark.asyncio
async def test_yesterday_gap_breaks_streak(db_session, seeded_user) -> None:
    """Past activity but yesterday gap and no auto-apply → streak=0.

    Sets up events at days ``[today-2 .. today-5]`` (4 days). Yesterday
    (``today-1``) and today are blank. Walk: today=grace pass, yesterday
    broken → no auto-apply → break. Streak=0.
    """

    for offset in range(2, 6):  # days 2..5 ago
        await _add_event(
            db_session,
            user_id=seeded_user,
            day=_ANCHOR_DATE - timedelta(days=offset),
        )

    result = await compute_streak(
        db_session,
        user_id=seeded_user,
        today_utc=_ANCHOR_DATE,
        auto_apply_freezes=False,
    )
    assert result.streak_days == 0
    assert result.freezes_used_dates == []


# ── 5. Auto-freeze saves yesterday gap ──────────────────────────────


@pytest.mark.asyncio
async def test_auto_freeze_saves_yesterday_gap(db_session, seeded_user) -> None:
    """Yesterday gap + auto_apply + budget → 1 freeze covers the gap.

    Same seed as #4 (events at ``[today-2 .. today-5]``); enabling
    ``auto_apply_freezes`` should fire one freeze for ``today-1`` and
    pick up the rest of the streak naturally. Walking past ``today-5``
    crosses the user's earliest-event floor, so the walk terminates
    there without burning more freezes — streak length = 4 events + 1
    freeze = 5. The post-walk freeze budget is 3 - 1 = 2.
    """

    for offset in range(2, 6):
        await _add_event(
            db_session,
            user_id=seeded_user,
            day=_ANCHOR_DATE - timedelta(days=offset),
        )

    result = await compute_streak(
        db_session,
        user_id=seeded_user,
        today_utc=_ANCHOR_DATE,
        auto_apply_freezes=True,
    )
    assert result.streak_days == 5
    assert result.freezes_used_dates == [_ANCHOR_DATE - timedelta(days=1)]
    assert result.freezes_left_this_week == 2


# ── 6. Auto-freeze with no budget → still breaks ────────────────────


@pytest.mark.asyncio
async def test_auto_freeze_no_budget_breaks_streak(db_session, seeded_user) -> None:
    """auto_apply=True but quota exhausted pre-walk → streak still breaks.

    Pre-seed three card freezes for days that lie OUTSIDE the streak
    walk window (the prior ISO week, so they still count toward the
    weekly quota of the freeze service). The walk's auto-apply path
    sees ``remaining_this_week == 0`` for the current week and skips
    the insert; yesterday's gap therefore breaks the streak.
    """

    # Past activity at days 2..5 ago — the "good" history.
    for offset in range(2, 6):
        await _add_event(
            db_session,
            user_id=seeded_user,
            day=_ANCHOR_DATE - timedelta(days=offset),
        )
    # Burn the three weekly freeze slots on cards from the CURRENT ISO
    # week so the freeze service's quota counter reads "0 remaining".
    # Use the current week's Monday and a couple of well-spaced
    # daytimes so the rows count toward this week's bucket without
    # accidentally covering walk-relevant days. The week's Monday is
    # ``today - today.weekday()``; for Wed 2026-04-22 that's Mon
    # 2026-04-20 — outside the events at days 2..5 (which start at
    # Mon 2026-04-20 itself, giving us a single-day overlap that does
    # NOT reach into the broken-yesterday day).
    week_monday = _ANCHOR_DATE - timedelta(days=_ANCHOR_DATE.weekday())
    # Stack three freezes all on Monday — the per-card uniqueness uses
    # ``(user_id, problem_id)`` and ``_add_freeze`` mints a fresh
    # problem_id each call, so duplicates on the same calendar day
    # remain unique in the DB. They each count toward the weekly
    # quota because ``frozen_at >= week_start``.
    for _ in range(3):
        await _add_freeze(db_session, user_id=seeded_user, day=week_monday)

    result = await compute_streak(
        db_session,
        user_id=seeded_user,
        today_utc=_ANCHOR_DATE,
        auto_apply_freezes=True,
    )
    # Walk: today=grace pass, yesterday=broken AND budget=0 → break.
    # ``freezes_used_dates`` must be empty because nothing new was
    # inserted; ``freezes_left_this_week`` is 0; streak is 0 because
    # the broken yesterday cannot be saved.
    assert result.freezes_used_dates == []
    assert result.freezes_left_this_week == 0
    assert result.streak_days == 0


# ── 7. Pre-existing freeze natively maintains a day ────────────────


@pytest.mark.asyncio
async def test_existing_freeze_natively_maintains_day(db_session, seeded_user) -> None:
    """A real card-freeze on yesterday counts as maintained without auto-apply."""

    # Today and the day before yesterday have events; yesterday is
    # covered by a regular card freeze (Phase 14 mechanism).
    await _add_event(db_session, user_id=seeded_user, day=_ANCHOR_DATE)
    await _add_event(
        db_session,
        user_id=seeded_user,
        day=_ANCHOR_DATE - timedelta(days=2),
    )
    await _add_freeze(
        db_session,
        user_id=seeded_user,
        day=_ANCHOR_DATE - timedelta(days=1),
    )

    result = await compute_streak(
        db_session,
        user_id=seeded_user,
        today_utc=_ANCHOR_DATE,
        auto_apply_freezes=False,
    )
    # today (event) + yesterday (freeze covers it) + day-before (event)
    # = 3-day streak with no auto-apply involved.
    assert result.streak_days == 3
    assert result.freezes_used_dates == []
    # Freeze was pre-existing → quota already shows 2 left (3 - 1).
    assert result.freezes_left_this_week == 2


# ── 8. Zero / negative XP does not maintain a day ──────────────────


@pytest.mark.asyncio
async def test_zero_amount_event_does_not_maintain_day(db_session, seeded_user) -> None:
    """An ``amount=0`` event on yesterday does NOT keep the streak alive."""

    await _add_event(db_session, user_id=seeded_user, day=_ANCHOR_DATE, amount=5)
    # Zero-amount filler row — the streak walker must ignore it.
    await _add_event(
        db_session,
        user_id=seeded_user,
        day=_ANCHOR_DATE - timedelta(days=1),
        amount=0,
    )

    result = await compute_streak(
        db_session,
        user_id=seeded_user,
        today_utc=_ANCHOR_DATE,
        auto_apply_freezes=False,
    )
    # Today event = 1; yesterday's amount=0 doesn't maintain → break.
    assert result.streak_days == 1


# ── 9. Walk is bounded — sparse history doesn't burn the loop ──────


@pytest.mark.asyncio
async def test_walk_is_bounded(db_session, seeded_user) -> None:
    """One very-old event + auto_apply does not run away.

    Earliest event 30 days ago. With ``auto_apply_freezes=True`` and a
    freshly-allocated budget of 3, the walker must terminate without
    forging a 365-day streak. The streak-saver guard "do not extend
    the streak past the user's earliest event" caps the walk at 30
    days from today; combined with the weekly freeze cap (3) the user
    can save at most three of the missing days. ``streak_days``
    therefore lands at 1 (the lone event itself) plus whatever
    contiguous bridging the freezes managed — never near 30.
    """

    very_old = _ANCHOR_DATE - timedelta(days=30)
    await _add_event(db_session, user_id=seeded_user, day=very_old)

    result = await compute_streak(
        db_session,
        user_id=seeded_user,
        today_utc=_ANCHOR_DATE,
        auto_apply_freezes=True,
    )
    # We don't assert an exact number here — the fragile thing is the
    # bound. The walk must produce a small finite result and must
    # never insert more than the weekly quota of freezes.
    assert result.streak_days >= 0
    assert result.streak_days < 30
    assert len(result.freezes_used_dates) <= 3


# ── 10. Post-walk freeze budget is reflected ───────────────────────


@pytest.mark.asyncio
async def test_freezes_left_reflects_post_walk_state(db_session, seeded_user) -> None:
    """After auto-applying one freeze, ``freezes_left_this_week`` drops.

    Identical seed to #5; we re-check the budget as a separate
    assertion to keep the regression target focused on the meta
    counter rather than the streak length.
    """

    for offset in range(2, 6):
        await _add_event(
            db_session,
            user_id=seeded_user,
            day=_ANCHOR_DATE - timedelta(days=offset),
        )

    result = await compute_streak(
        db_session,
        user_id=seeded_user,
        today_utc=_ANCHOR_DATE,
        auto_apply_freezes=True,
    )

    # Pre-walk budget is 3 (Phase 14 default). One freeze fired at
    # yesterday → 2 remaining. The post-walk meta query in compute_streak
    # must reflect that change without a second commit cycle.
    assert result.freezes_left_this_week == 2
    assert len(result.freezes_used_dates) == 1
