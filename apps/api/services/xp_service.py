"""XP service — Phase 16c Story 2 backend (Subagent A scope).

Two layers:

1. **Pure functions** (``compute_xp``, ``tier_name``, ``level_progress_pct``)
   — deterministic, no DB, no time, easy to unit-test. These are the
   single source of truth for the gamification math; all routers and
   integration code should call them rather than re-implementing the
   formula. Story 1 #7 + Story 2 #2.

2. **DB awarders** (``award_card_xp``, ``award_room_xp``,
   ``get_user_xp_total``, ``get_xp_events_in_range``) — async
   ``AsyncSession`` helpers that insert ``xp_events`` rows or read
   aggregates. Idempotent on the anti-spam unique index: a duplicate
   ``(user_id, source_id, today)`` raises ``IntegrityError`` which the
   awarders swallow and return ``None`` (Story 2 #4 — never fail the
   caller's transaction; just log).

Determinism table for ``compute_xp`` (matches the spec asserts in
``tests/services/test_xp_service.py``):

    card correct, layer=2, no hint, fast            → 4
    card wrong (correctness=0.0)                    → 1   (consolation +1)
    card half-credit, layer=3, no hint              → 2   (1 + 1)
    room_complete, task_count=15                    → 100 (cap)
    hacking_room_complete, task_count=15            → 200 (cap)

Tier bands (Story 1 #3 — flag 4 signed off 2026-04-24):

    Bronze   0..499
    Silver   500..1999
    Gold     2000..4999
    Platinum 5000..9999
    Diamond  10000+

Each band is split into thirds (sub-tiers I/II/III) so users see
movement before crossing into the next major tier. Diamond is
open-ended so it stays at "Diamond I" forever — the brief explicitly
calls this out (the III sub-tier would never trigger).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.xp_event import XpEvent


_log = logging.getLogger(__name__)


# ── Tier system ─────────────────────────────────────────────────────


# (label, low_inclusive, high_inclusive_or_None_for_open_band)
LEVEL_BANDS: list[tuple[str, int, Optional[int]]] = [
    ("Bronze", 0, 499),
    ("Silver", 500, 1999),
    ("Gold", 2000, 4999),
    ("Platinum", 5000, 9999),
    ("Diamond", 10000, None),
]


def _resolve_band(xp_total: int) -> tuple[str, int, Optional[int]]:
    """Return ``(label, low, high)`` for the band ``xp_total`` falls in.

    ``xp_total`` is clamped to ``0`` if negative — defensive against any
    upstream subtraction (hint penalties) that overshoots.
    """
    xp = max(0, xp_total)
    for label, low, high in LEVEL_BANDS:
        if high is None or xp <= high:
            return label, low, high
    # Unreachable — Diamond's high is None so the loop always returns.
    return LEVEL_BANDS[-1]


def tier_name(xp_total: int) -> str:
    """Return the user-facing rank string for a given XP total.

    Closed bands split into three equal-ish thirds: the first third
    yields ``"I"``, the second ``"II"``, the third ``"III"``. The
    open-ended Diamond band always returns ``"Diamond I"`` (Story 1 #3
    notes "no III sub-tier, open band").

    Examples (asserted by tests):

        tier_name(0)     -> "Bronze I"
        tier_name(166)   -> "Bronze II"
        tier_name(333)   -> "Bronze III"
        tier_name(500)   -> "Silver I"
        tier_name(2000)  -> "Gold I"
        tier_name(10000) -> "Diamond I"
        tier_name(50000) -> "Diamond I"
    """
    label, low, high = _resolve_band(xp_total)
    if high is None:
        return f"{label} I"
    band_size = high - low + 1
    third = band_size // 3
    offset = max(0, xp_total) - low
    if offset < third:
        sub = "I"
    elif offset < 2 * third:
        sub = "II"
    else:
        sub = "III"
    return f"{label} {sub}"


def level_progress_pct(xp_total: int) -> int:
    """Integer 0..100 — progress through the current band.

    The open-ended Diamond band has no upper bound, so we return ``0``
    (there is no "next tier" to make progress towards). For closed
    bands, value is ``floor((xp - low) * 100 / band_size)`` so the
    boundary XP that crosses into the next band reads ``0`` again.

        level_progress_pct(0)    -> 0
        level_progress_pct(250)  -> 50
        level_progress_pct(499)  -> 99
        level_progress_pct(500)  -> 0
        level_progress_pct(1500) -> 66
    """
    label, low, high = _resolve_band(xp_total)
    if high is None:
        return 0
    band_size = high - low + 1
    offset = max(0, xp_total) - low
    pct = (offset * 100) // band_size
    return max(0, min(100, pct))


# ── Pure XP formula ──────────────────────────────────────────────────


_AMOUNT_MIN = -5
_AMOUNT_MAX = 200


def _clamp_amount(amount: int) -> int:
    """Snap ``amount`` to the DB CHECK range so callers never violate it."""
    return max(_AMOUNT_MIN, min(_AMOUNT_MAX, amount))


EventType = Literal["card", "room_complete", "hacking_room_complete", "manual"]


def compute_xp(
    *,
    event_type: EventType,
    difficulty_layer: int = 1,
    correctness: float = 1.0,
    hints_used: int = 0,
    answer_time_ms: Optional[int] = None,
    task_count: int = 0,
    is_hacking: bool = False,
    manual_amount: int = 0,
) -> int:
    """Compute the XP amount for one event. Pure — no I/O, no clock.

    Story 2 #2 formula:

    * ``card`` correct (``correctness == 1.0``):
      base = ``difficulty_layer × correctness``. Plus optional bonuses:

      - ``+1`` when ``hints_used == 0`` (no-hint bonus).
      - ``+1`` when ``answer_time_ms < 10_000`` AND
        ``difficulty_layer >= 2`` (fast bonus; the difficulty gate
        prevents farming layer-1 cards for speed).

    * ``card`` partial (``correctness == 0.5``):
      base = ``round(difficulty_layer × correctness)``. No no-hint or
      fast bonus (the answer wasn't fully right).

    * ``card`` wrong (``correctness == 0.0``):
      ``+1`` consolation (Story 2 #2: kill the "don't try" pattern).
      Capped at ``+1`` regardless of difficulty.

    * ``room_complete``: ``+10 × task_count`` capped at ``+100``.
    * ``hacking_room_complete`` *or* ``room_complete`` with
      ``is_hacking=True``: ``+20 × task_count`` capped at ``+200``.
    * ``manual``: returns ``manual_amount`` clamped to the CHECK range.

    All branches end with ``_clamp_amount`` so the result always lands
    inside ``[-5, 200]``.
    """
    if event_type == "manual":
        return _clamp_amount(int(manual_amount))

    if event_type == "card":
        if correctness <= 0.0:
            # Wrong-but-attempted thin reward. Capped at +1, no stacking.
            return _clamp_amount(1)

        base = max(0, int(round(difficulty_layer * correctness)))
        bonus = 0
        if correctness >= 1.0:
            # Bonuses only stack on a fully-correct answer.
            if hints_used == 0:
                bonus += 1
            if (
                answer_time_ms is not None
                and answer_time_ms < 10_000
                and difficulty_layer >= 2
            ):
                bonus += 1
        return _clamp_amount(base + bonus)

    if event_type == "room_complete" or event_type == "hacking_room_complete":
        is_hack = is_hacking or event_type == "hacking_room_complete"
        per_task = 20 if is_hack else 10
        cap = 200 if is_hack else 100
        raw = per_task * max(0, task_count)
        return _clamp_amount(min(cap, raw))

    # Unknown event_type — explicit error so callers can't silently
    # award 0 XP forever.
    raise ValueError(f"Unknown event_type: {event_type!r}")


# ── DB awarders ──────────────────────────────────────────────────────


async def award_card_xp(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    difficulty_layer: int,
    correctness: float,
    hints_used: int = 0,
    answer_time_ms: Optional[int] = None,
) -> Optional[XpEvent]:
    """Insert one ``xp_events`` row for a card answer.

    Returns the new ``XpEvent``, or ``None`` if the anti-spam unique
    index rejected the insert because the user already earned XP for
    this ``problem_id`` on the current UTC day. The caller's transaction
    is rolled back to a savepoint behind the scenes so a same-day
    duplicate does not fail the practice-result write (Story 2 #4).
    """
    amount = compute_xp(
        event_type="card",
        difficulty_layer=difficulty_layer,
        correctness=correctness,
        hints_used=hints_used,
        answer_time_ms=answer_time_ms,
    )
    return await _insert_event_safe(
        db,
        user_id=user_id,
        amount=amount,
        source="practice_result",
        source_id=problem_id,
        metadata_json={
            "difficulty_layer": difficulty_layer,
            "correctness": correctness,
            "hints_used": hints_used,
            "answer_time_ms": answer_time_ms,
        },
    )


async def award_room_xp(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    room_id: uuid.UUID,
    task_count: int,
    is_hacking: bool,
) -> Optional[XpEvent]:
    """Insert one ``xp_events`` row for completing a room.

    Hacking rooms award the ``×2`` bonus (Story 2 #2 — flag 5 signed
    off). Same anti-spam guard as ``award_card_xp``: a second completion
    of the same room on the same UTC day returns ``None``.
    """
    event_type: EventType = "hacking_room_complete" if is_hacking else "room_complete"
    amount = compute_xp(
        event_type=event_type,
        task_count=task_count,
        is_hacking=is_hacking,
    )
    return await _insert_event_safe(
        db,
        user_id=user_id,
        amount=amount,
        source="hacking_room_complete" if is_hacking else "room_complete",
        source_id=room_id,
        metadata_json={
            "task_count": task_count,
            "is_hacking": is_hacking,
        },
    )


async def _insert_event_safe(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount: int,
    source: str,
    source_id: Optional[uuid.UUID],
    metadata_json: Optional[dict],
) -> Optional[XpEvent]:
    """Insert one event, swallowing the dedup IntegrityError.

    Why a savepoint: AsyncSession.add + commit raises IntegrityError on
    the unique-index violation. Without a savepoint the parent tx is
    poisoned. We open a nested SAVEPOINT (``begin_nested``) so a dup
    rolls back **just that statement** while the caller's outer
    transaction (e.g. the practice-result write) stays clean.
    """
    event = XpEvent(
        user_id=user_id,
        amount=amount,
        source=source,
        source_id=source_id,
        metadata_json=metadata_json,
        earned_at=datetime.now(timezone.utc),
    )
    try:
        async with db.begin_nested():
            db.add(event)
        await db.flush()
        return event
    except IntegrityError as exc:
        # Same-day duplicate or amount out of range — log and bail.
        # Caller's outer transaction is intact thanks to begin_nested.
        _log.warning(
            "xp_service: insert rejected (likely same-day dedup) "
            "user_id=%s source=%s source_id=%s amount=%s err=%s",
            user_id,
            source,
            source_id,
            amount,
            exc.orig if hasattr(exc, "orig") else exc,
        )
        return None


async def get_user_xp_total(db: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Return ``SUM(amount)`` for the user. ``0`` for new accounts."""
    stmt = select(func.coalesce(func.sum(XpEvent.amount), 0)).where(
        XpEvent.user_id == user_id
    )
    total = (await db.execute(stmt)).scalar_one()
    return int(total or 0)


async def get_xp_events_in_range(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> list[XpEvent]:
    """Return events with ``start_utc <= earned_at <= end_utc`` ordered
    oldest-first. Boundary inclusive on both sides — used by the streak
    walker (Subagent B) and the heatmap aggregation."""
    stmt = (
        select(XpEvent)
        .where(
            XpEvent.user_id == user_id,
            XpEvent.earned_at >= start_utc,
            XpEvent.earned_at <= end_utc,
        )
        .order_by(XpEvent.earned_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
