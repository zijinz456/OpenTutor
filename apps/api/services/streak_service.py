"""Streak computation service — Phase 16c Story 3 (Streak + Freeze).

This module implements the daily-streak walk used by the gamification
dashboard. The ADHD-safe contract from the plan:

* A day is **maintained** when the user has at least one positive XP
  event that day, OR when an active Freeze Token (Phase 14 T1) covers
  the day.
* Today is **grace** — its absence does not break a prior streak. A
  totally-empty account still produces ``streak_days == 0``; a 5-day
  streak survives a 0-XP today until tomorrow's compute.
* When ``auto_apply_freezes=True`` and the user still has weekly freeze
  budget, a broken day inside the walk is retroactively saved by
  inserting a fresh ``FreezeToken`` row keyed to that day. This is the
  only side-effect path; the read-only path leaves the DB untouched.

The module uses Subagent A's contract:

* ``models.xp_event.XpEvent`` — table ``xp_events`` with at least
  ``user_id``, ``amount``, ``earned_at`` columns.
* ``services.xp_service.get_xp_events_in_range`` — fetches positive XP
  events in ``[start_utc, end_utc)`` for a user.

Spec ambiguity notes (resolved here):

* The plan says "today is grace, always maintained" but also "new
  account → streak_days = 0". We resolve by treating today's grace as
  non-counting: today contributes +1 only when it has a real event or
  freeze; otherwise it passes through without breaking the streak but
  also without adding to it. A new account therefore returns 0 (no real
  maintenance anywhere); a "today only" account returns 1.
* Auto-freeze must not extend the streak into pre-history. We bound the
  walk at the user's earliest XP event date — once we walk past it, no
  more freezes fire and the loop terminates. This keeps the freeze
  count honest ("1 freeze covered the gap that broke an otherwise solid
  streak", not "10 freezes burned to fabricate a 200-day streak from a
  10-event account").
* The walk also has a hard 366-day ceiling so a pathological account
  with sparse very-old events cannot OOM the loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import as_utc, utcnow
from models.freeze_token import FreezeToken
from models.xp_event import XpEvent
from services import freeze as freeze_service
from services import xp_service

# Defensive ceiling on the walk. ADHD users with year-long streaks are
# rare but possible; 366 covers a leap year + the today-grace tile.
_WALK_MAX_DAYS: int = 366

# Lifetime in hours of a streak-saver freeze. Aligned with the regular
# Phase 14 freeze TTL so the existing ``active_frozen_problem_ids``
# query (which compares ``expires_at > now``) treats streak-saver and
# card freezes uniformly.
_FREEZE_HOURS: int = 24


@dataclass(frozen=True)
class StreakResult:
    """Outcome of a single :func:`compute_streak` call.

    Attributes:
        streak_days: Number of consecutive maintained days ending on
            today (today inclusive). 0 for an account with no
            qualifying activity. Always ``>= 0``.
        freezes_used_dates: List of UTC dates for which an auto-freeze
            was inserted during this call. Empty when
            ``auto_apply_freezes=False`` or when no broken days were
            found within the walk's reach. Order is walk order
            (newest gap first).
        freezes_left_this_week: Remaining freeze budget for the user's
            current ISO week, AFTER any auto-applied freezes inserted
            during this call. Caller can surface this directly on the
            dashboard ("2 freezes left").
    """

    streak_days: int
    freezes_used_dates: list[date]
    freezes_left_this_week: int


def _day_bounds_utc(day: date) -> tuple[datetime, datetime]:
    """Return ``[00:00 UTC, +24h)`` window for ``day`` as tz-aware datetimes.

    Used both as the XP-event range query bracket and as the
    ``frozen_at`` / ``expires_at`` pair when minting a streak-saver
    freeze. Naming both ends ``utc`` in the call site reinforces that
    callers must never feed a naive datetime here.
    """

    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _week_start_utc_for(day: date) -> datetime:
    """Return Monday 00:00 UTC of the ISO week containing ``day``.

    Mirrors :func:`services.freeze._week_start_utc` (which takes a
    datetime). We accept a ``date`` here so the streak walk can ask
    "what bucket does day-N belong to?" without re-wrapping every
    iteration into a datetime.
    """

    weekday = day.weekday()  # Monday=0
    monday = day - timedelta(days=weekday)
    return datetime.combine(monday, time.min, tzinfo=timezone.utc)


async def _fetch_xp_active_dates(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    earliest: date,
    latest: date,
) -> set[date]:
    """Return the set of UTC dates where the user has ``amount > 0`` events.

    One query covers the whole walk window to avoid 365 round-trips. We
    rely on Subagent A's :func:`xp_service.get_xp_events_in_range`
    contract for the SQL — this function only reshapes the rows into a
    date-set the walk can ``in``-test in O(1).
    """

    start = datetime.combine(earliest, time.min, tzinfo=timezone.utc)
    # ``get_xp_events_in_range`` is half-open [start, end); add a day to
    # ensure the latest day is included regardless of which boundary
    # convention the helper picks.
    end = datetime.combine(latest, time.min, tzinfo=timezone.utc) + timedelta(days=1)

    events = await xp_service.get_xp_events_in_range(
        db, user_id=user_id, start_utc=start, end_utc=end
    )
    active: set[date] = set()
    for event in events:
        amount = getattr(event, "amount", 0)
        if amount is None or amount <= 0:
            # Non-positive events (e.g. hint debits in Phase 16d) never
            # maintain a streak — only earnings count.
            continue
        earned_at = getattr(event, "earned_at", None)
        if earned_at is None:
            continue
        active.add(as_utc(earned_at).date())
    return active


async def _fetch_active_freeze_dates(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> set[date]:
    """Return the set of UTC dates covered by any of the user's freeze tokens.

    A freeze "covers" a day when ``frozen_at <= 00:00 UTC of day <
    expires_at``. We pull every token for the user (a learner has at
    most a few dozen lifetime — no pagination needed) and expand each
    into a per-day membership set. Streak-saver freezes (problem_id
    NULL, single-day window) and card freezes (problem_id non-NULL,
    24h window) are treated identically by this lookup.
    """

    rows = await db.execute(
        select(FreezeToken.frozen_at, FreezeToken.expires_at).where(
            FreezeToken.user_id == user_id
        )
    )
    covered: set[date] = set()
    for frozen_at, expires_at in rows.all():
        if frozen_at is None or expires_at is None:
            continue
        f_start = as_utc(frozen_at).date()
        f_end = as_utc(expires_at).date()
        cur = f_start
        # ``expires_at`` is exclusive on its day boundary; iterate while
        # ``cur < f_end``. For a 24h window starting at 00:00 UTC this
        # yields exactly one date; for a 25-hour overlap (clock skew)
        # it yields two — both correct under the "covers the day" rule.
        while cur < f_end:
            covered.add(cur)
            cur += timedelta(days=1)
    return covered


async def _earliest_event_date(db: AsyncSession, *, user_id: uuid.UUID) -> date | None:
    """Return the user's oldest XP-positive day, or None if no events exist.

    The walk uses this as a hard floor: once we cross it backwards we
    stop trying to fire freezes. Without this bound, a user with one
    XP event and remaining freezes could silently fabricate a streak
    365 days long — see the spec ambiguity note in the module docstring.
    """

    stmt = (
        select(XpEvent.earned_at)
        .where(XpEvent.user_id == user_id, XpEvent.amount > 0)
        .order_by(XpEvent.earned_at.asc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    return as_utc(row[0]).date()


async def compute_streak(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    today_utc: date | None = None,
    auto_apply_freezes: bool = False,
) -> StreakResult:
    """Walk backwards from ``today_utc`` and report the user's current streak.

    Args:
        db: Active async SQLAlchemy session. Owned by the caller. We
            commit once at the end of the walk if (and only if) we
            inserted at least one auto-freeze; pure read calls do not
            touch the transaction.
        user_id: User whose streak to compute. Required keyword to keep
            call sites self-documenting on coordination boundaries.
        today_utc: Override for "today" — defaults to
            ``datetime.now(timezone.utc).date()``. Tests use this to
            anchor a deterministic walk window.
        auto_apply_freezes: When True, insert a streak-saver
            ``FreezeToken`` row each time the walk hits a broken day
            and the user still has weekly budget. When False (default),
            the walk is read-only and stops at the first broken day
            without touching the DB.

    Returns:
        :class:`StreakResult` — see its docstring for field semantics.
        ``freezes_left_this_week`` reflects the post-walk state, so the
        caller can render the dashboard counter without a second query.
    """

    today = today_utc or utcnow().date()

    # ── Pre-walk: gather XP-active and freeze-covered dates ──────────
    earliest_event = await _earliest_event_date(db, user_id=user_id)
    if earliest_event is None:
        # Brand-new account. Today's grace alone never produces a
        # streak — without any positive event in history the user has
        # not yet "started" a streak. Confirm via freezes too: if the
        # user has only freeze tokens (no XP events ever), we treat
        # them as inactive for streak purposes — freezes save streaks,
        # they don't bootstrap them.
        _, meta = await freeze_service.can_freeze(db, user_id)
        return StreakResult(
            streak_days=0,
            freezes_used_dates=[],
            freezes_left_this_week=int(meta["remaining"]),
        )

    walk_floor = min(earliest_event, today - timedelta(days=_WALK_MAX_DAYS))
    xp_dates = await _fetch_xp_active_dates(
        db, user_id=user_id, earliest=walk_floor, latest=today
    )
    freeze_dates = await _fetch_active_freeze_dates(db, user_id=user_id)

    # ── Pre-walk freeze budget snapshot, keyed by ISO week ───────────
    # The walk may need to ask "how many freezes does the user still
    # have for the week containing day-N?" multiple times for distinct
    # weeks. We initialise the per-week counter from the live service
    # (Phase 14 quota = 3/week) and decrement locally as we mint new
    # tokens; that way the auto-freeze cap is enforced without round-
    # tripping per gap.
    _, current_meta = await freeze_service.can_freeze(db, user_id)
    weekly_remaining: dict[datetime, int] = {}
    week_start_now = _week_start_utc_for(today)
    weekly_remaining[week_start_now] = int(current_meta["remaining"])

    inserted_freezes: list[date] = []

    # ── The walk itself ──────────────────────────────────────────────
    streak = 0
    day = today
    walked = 0

    while walked < _WALK_MAX_DAYS:
        is_event = day in xp_dates
        is_freeze = day in freeze_dates
        maintained = is_event or is_freeze

        if maintained:
            streak += 1
        elif day == today:
            # Today's grace: absent activity does not break a prior
            # streak, but contributes nothing on its own.
            pass
        else:
            # Broken day. Either fire a streak-saver or stop.
            if not auto_apply_freezes:
                break

            # Don't fabricate streaks before the user's first event.
            if day < earliest_event:
                break

            # Compute the freeze budget for the ISO week of this day.
            week_start = _week_start_utc_for(day)
            if week_start not in weekly_remaining:
                # New week we haven't probed yet — refresh from the
                # service so cross-week walks get accurate quotas.
                _, meta = await freeze_service.can_freeze(db, user_id)
                weekly_remaining[week_start] = int(meta["remaining"])
            if weekly_remaining[week_start] <= 0:
                break

            # Mint the streak-saver freeze. ``problem_id=None`` is the
            # explicit marker (Phase 14 model now allows NULL after
            # Subagent A's migration).
            day_start, day_end = _day_bounds_utc(day)
            token = FreezeToken(
                user_id=user_id,
                problem_id=None,
                frozen_at=day_start,
                expires_at=day_start + timedelta(hours=_FREEZE_HOURS),
            )
            db.add(token)
            inserted_freezes.append(day)
            weekly_remaining[week_start] -= 1
            # Make this day immediately count for the walk's invariant
            # — a follow-up query on freeze_tokens would re-find it.
            freeze_dates.add(day)
            streak += 1

        day -= timedelta(days=1)
        walked += 1

    # ── Persist auto-freezes (if any) and refresh the post-walk meta ─
    if inserted_freezes:
        await db.commit()

    _, post_meta = await freeze_service.can_freeze(db, user_id)
    return StreakResult(
        streak_days=streak,
        freezes_used_dates=inserted_freezes,
        freezes_left_this_week=int(post_meta["remaining"]),
    )


__all__ = ["StreakResult", "compute_streak"]
