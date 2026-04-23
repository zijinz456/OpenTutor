"""Freeze-token service — Phase 14 T1.

Four coroutines expose the complete freeze lifecycle:

* :func:`can_freeze` — quota inspection (used by the status endpoint and
  by ``freeze_card`` for the 409 guard).
* :func:`freeze_card` — write a new token; raise
  :class:`ConflictError` on quota-exceeded / already-frozen-card.
* :func:`active_frozen_problem_ids` — the list consumed by
  ``services.daily_plan.select_daily_plan`` to hide frozen cards from
  the session batch.
* :func:`get_freeze_status` — one-shot payload for the status endpoint.

Quota semantics
---------------

Three freezes per **ISO calendar week** in UTC (Monday 00:00 UTC is the
boundary). The count is ``SELECT COUNT(*) FROM freeze_tokens WHERE
user_id = ? AND frozen_at >= week_start`` — there is no ``week_start``
column because "rows whose ``frozen_at`` is in the current week" is the
same predicate, and materialising the bucket would duplicate state.

Per-card lifetime cap
---------------------

The DB-level ``UniqueConstraint("user_id", "problem_id")`` gives us a
single-row invariant: one card freezes once per lifetime. We surface
that as a 409 at the service layer rather than letting the
``IntegrityError`` escape, because callers should be able to distinguish
"quota full" from "already frozen" without parsing SQLSTATE.

Return types
------------

The service intentionally raises a private :class:`ConflictError`
instead of ``HTTPException`` — the router adapts that to HTTP 409. This
keeps the service unit-testable without a FastAPI import.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import utcnow
from models.freeze_token import FreezeToken


FREEZE_QUOTA_PER_WEEK: int = 3
"""Hard cap — three freezes per user per UTC ISO week. Not configurable
at runtime; see critic C1 (``plan/adhd_ux_full_phase14.md``) for the
rationale — a variable quota invites "freeze every hard card" avoidance
and MASTER §8 explicitly calls it out as a dopamine trap."""

FREEZE_EXPIRY_HOURS: int = 24
"""Lifetime of a single freeze. After ``frozen_at + 24h`` the card
re-enters the daily-plan queue at its original FSRS state — we never
reset ``next_review_at`` so the learner's debt is preserved."""


class ConflictError(Exception):
    """Raised when a freeze would violate the quota or lifetime cap.

    ``reason`` is one of ``"weekly_cap_exceeded"`` /
    ``"already_frozen"`` so the router can map each to the appropriate
    ``detail`` string without string-matching the message.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ActiveFreeze:
    """Serializable row for the status endpoint — problem + expiry only."""

    problem_id: uuid.UUID
    expires_at: datetime


def _week_start_utc(now: datetime) -> datetime:
    """Return the UTC midnight of the Monday of the ISO week containing ``now``.

    ``datetime.isocalendar()`` would return the week number but we need
    the actual timestamp boundary for the SQL filter. Building it from
    ``weekday()`` (Mon=0) keeps us in tz-aware ``datetime`` land — no
    cross-module helpers and no date-vs-datetime coercion bugs.
    """

    assert now.tzinfo is not None, "now must be tz-aware"
    utc_now = now.astimezone(timezone.utc)
    midnight = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=utc_now.weekday())


async def _count_freezes_this_week(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> int:
    """Count rows this user created in the current ISO week (UTC).

    Split out so :func:`can_freeze` and :func:`freeze_card` share one
    SQL plan and tests can monkeypatch a single call site.
    """

    now = now or utcnow()
    week_start = _week_start_utc(now)
    stmt = select(func.count(FreezeToken.id)).where(
        FreezeToken.user_id == user_id,
        FreezeToken.frozen_at >= week_start,
    )
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


async def can_freeze(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> tuple[bool, dict[str, int]]:
    """Check whether ``user_id`` still has tokens left this calendar week.

    Args:
        db: Active async SQLAlchemy session (caller owns the transaction).
        user_id: User under inspection.
        now: Override for "now" (tests only — defaults to :func:`utcnow`).

    Returns:
        ``(allowed, meta)`` where ``meta`` is ``{"used": N, "quota": 3,
        "remaining": 3 - N}``. ``allowed`` is true iff ``remaining > 0``.
        The tuple shape lets callers either branch on the bool or forward
        ``meta`` to the wire schema without a second query.
    """

    used = await _count_freezes_this_week(db, user_id, now=now)
    remaining = max(0, FREEZE_QUOTA_PER_WEEK - used)
    meta = {
        "used": used,
        "quota": FREEZE_QUOTA_PER_WEEK,
        "remaining": remaining,
    }
    return remaining > 0, meta


async def freeze_card(
    db: AsyncSession,
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> FreezeToken:
    """Persist a new freeze row for ``(user_id, problem_id)``.

    The quota + uniqueness checks run on the server inside one async
    session; we commit on success so ``expires_at`` is immediately
    visible to :func:`active_frozen_problem_ids`.

    Args:
        db: Active async SQLAlchemy session. We call ``commit`` here —
            matching the Phase 5 ``interview_sessions`` write pattern
            where the service owns durability rather than forcing every
            router to remember it.
        user_id: Owner of the freeze.
        problem_id: Target practice problem.
        now: Override for "now" (tests only — defaults to :func:`utcnow`).

    Returns:
        The freshly-inserted :class:`FreezeToken` row, refreshed so
        ``id`` and the server defaults are populated.

    Raises:
        ConflictError: ``reason="weekly_cap_exceeded"`` when the user
            already spent three freezes this week, or
            ``reason="already_frozen"`` when a row for
            ``(user_id, problem_id)`` already exists (lifetime cap).
    """

    now = now or utcnow()

    # ── Pre-check 1: per-card lifetime uniqueness ──
    existing_stmt = select(FreezeToken.id).where(
        FreezeToken.user_id == user_id,
        FreezeToken.problem_id == problem_id,
    )
    existing = await db.execute(existing_stmt)
    if existing.scalar_one_or_none() is not None:
        raise ConflictError("already_frozen", "This card has already been frozen once.")

    # ── Pre-check 2: weekly quota ──
    used = await _count_freezes_this_week(db, user_id, now=now)
    if used >= FREEZE_QUOTA_PER_WEEK:
        raise ConflictError(
            "weekly_cap_exceeded",
            f"Weekly freeze quota reached ({used}/{FREEZE_QUOTA_PER_WEEK}). "
            "Resets Monday 00:00 UTC.",
        )

    # ── Insert ──
    token = FreezeToken(
        user_id=user_id,
        problem_id=problem_id,
        frozen_at=now,
        expires_at=now + timedelta(hours=FREEZE_EXPIRY_HOURS),
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)
    return token


async def active_frozen_problem_ids(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> list[uuid.UUID]:
    """Return problem_ids whose freeze is still active (``expires_at > now``).

    Consumed by ``services.daily_plan.select_daily_plan`` via the
    ``excluded_ids`` kwarg. Returns a plain list (not a set) so the call
    site's type signature stays symmetrical with the router's query
    result type; the selector coerces to ``set()`` internally.
    """

    now = now or utcnow()
    stmt = select(FreezeToken.problem_id).where(
        FreezeToken.user_id == user_id,
        FreezeToken.expires_at > now,
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


async def get_freeze_status(
    db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, object]:
    """One-shot payload for ``GET /api/freeze/status``.

    Returns ``{"quota_remaining": int, "weekly_used": int,
    "active_freezes": [{"problem_id": UUID, "expires_at": datetime}]}``.
    Kept as a plain ``dict`` rather than a pydantic model so the router
    owns wire-shape concerns — the service stays DB-only.
    """

    now = now or utcnow()
    _, meta = await can_freeze(db, user_id, now=now)

    active_stmt = (
        select(FreezeToken.problem_id, FreezeToken.expires_at)
        .where(
            FreezeToken.user_id == user_id,
            FreezeToken.expires_at > now,
        )
        .order_by(FreezeToken.expires_at.asc())
    )
    active_result = await db.execute(active_stmt)
    active_freezes = [
        {"problem_id": problem_id, "expires_at": expires_at}
        for problem_id, expires_at in active_result.all()
    ]

    return {
        "quota_remaining": meta["remaining"],
        "weekly_used": meta["used"],
        "active_freezes": active_freezes,
    }


async def unfreeze_card(
    db: AsyncSession,
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> bool:
    """Expire the freeze for ``(user_id, problem_id)`` immediately.

    Does NOT delete the row — critic C8 on
    ``plan/adhd_ux_full_phase14.md``: deleting would refund the weekly
    quota slot (the count query drops with the row), letting a learner
    freeze/unfreeze/re-freeze the same card all week. Instead we set
    ``expires_at = now`` so:

    * ``active_frozen_problem_ids`` drops the card immediately (card
      re-enters the daily-plan queue on the next request),
    * the row still counts toward the weekly quota
      (``_count_freezes_this_week`` is keyed on ``frozen_at``),
    * the per-card lifetime ``UniqueConstraint`` still applies, so the
      user cannot re-freeze the same card later in the week.

    Returns ``True`` when a row existed and was expired, ``False`` when
    nothing matched (the router maps this to 404).
    """

    now = now or utcnow()
    stmt = select(FreezeToken).where(
        FreezeToken.user_id == user_id,
        FreezeToken.problem_id == problem_id,
    )
    result = await db.execute(stmt)
    token = result.scalar_one_or_none()
    if token is None:
        return False

    token.expires_at = now
    await db.commit()
    return True


__all__ = [
    "ActiveFreeze",
    "ConflictError",
    "FREEZE_EXPIRY_HOURS",
    "FREEZE_QUOTA_PER_WEEK",
    "active_frozen_problem_ids",
    "can_freeze",
    "freeze_card",
    "get_freeze_status",
    "unfreeze_card",
]
