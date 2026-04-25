"""Badge catalog + predicate evaluation + idempotent award.

Phase 16c Bundle C — Subagent A scope. Three layers:

1. **Catalog** (:data:`CATALOG`) — the canonical 10-badge list defined
   in Bundle C spec A.2. Each entry pairs a stable ``key`` with
   user-facing copy (``title``, ``description``, ``hint``) and a
   deterministic predicate. Catalog is the single source of truth for
   "what badges exist"; the router maps over it to render the
   shelf/profile, so adding a badge is a one-line edit here.

2. **Predicates** — ``async`` functions ``(db, *, user_id) -> bool``
   that return True when the user is currently eligible for that
   badge. Each predicate is a single SQL query (or one tier-service
   call); they must be deterministic and cheap so the
   ``GET /api/gamification/badges`` endpoint can run all 10 on every
   request without flaring DB load.

3. **Award helpers** — :func:`award_if_eligible` and
   :func:`award_all_eligible` insert ``user_badges`` rows, swallowing
   ``IntegrityError`` from the unique ``(user_id, badge_key)`` index
   so a same-(user, badge) re-award is a silent no-op (Bundle C spec
   D.1 — "one-time unlock per spec").

The service exposes no badge-awarding HTTP endpoint: caller code
(quiz_submission, room_completion, etc.) wires
``award_all_eligible`` after relevant gamification events. The
read-only :func:`list_unlocked` is what the router calls.

Notes on individual predicates:

* ``_pred_no_hint`` reads ``xp_events.metadata_json->hints_used`` —
  Bundle B's :func:`services.xp_service.award_card_xp` stores
  ``hints_used`` in the event metadata, so this badge IS testable
  without a schema change. If the metadata blob is absent (legacy
  rows, manual grants) the predicate treats those rows as
  "unknown — skip" and only fires on rows that explicitly record
  ``hints_used == 0`` AND ``correctness == 1.0``.
* ``_pred_comeback`` looks at gaps in the user's XP-event timeline.
  We avoid the more elaborate window-function variant (sqlite
  doesn't support ``LAG()`` reliably) and instead pull the user's
  distinct event days into Python, scan for a 3+ day gap whose
  resolution lands within the trailing 7 days, and return True on
  the first hit.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from sqlalchemy import and_, exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from libs.datetime_utils import as_utc, utcnow
from models.learning_path import LearningPath, PathRoom
from models.user_badge import UserBadge
from models.xp_event import XpEvent
from services import streak_service, xp_service


_log = logging.getLogger(__name__)


# ── Predicate type alias ────────────────────────────────────────────


# Predicate signature: (db, *, user_id) -> awaitable[bool]. Catalog
# entries hold the function reference; the router never calls
# predicates directly — it goes through :func:`evaluate_all`.
Predicate = Callable[..., Awaitable[bool]]


# ── Catalog dataclass ───────────────────────────────────────────────


@dataclass(frozen=True)
class BadgeDef:
    """One canonical badge definition.

    Attributes:
        key: Stable string identifier (matches ``user_badges.badge_key``).
        title: Short user-facing label, e.g. ``"First card"``.
        description: One-line "what it means" — surfaced under the
            badge title on the profile shelf.
        hint: Short "how to get it" — used by the locked-state UI to
            give a calm nudge without grind framing.
        predicate: Async callable returning True iff the user is
            currently eligible to unlock this badge.
    """

    key: str
    title: str
    description: str
    hint: str
    predicate: Predicate


# ── Predicate implementations ───────────────────────────────────────


async def _pred_first_card(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True after the user has at least one ``practice_result`` XP event.

    Single SQL: ``EXISTS (SELECT 1 FROM xp_events WHERE user_id=:u AND
    source='practice_result' LIMIT 1)``.
    """

    stmt = select(
        exists().where(
            and_(
                XpEvent.user_id == user_id,
                XpEvent.source == "practice_result",
            )
        )
    )
    return bool((await db.execute(stmt)).scalar())


async def _pred_first_room(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True after the user has completed any room (standard or hacking).

    Both ``room_complete`` and ``hacking_room_complete`` xp events count.
    """

    stmt = select(
        exists().where(
            and_(
                XpEvent.user_id == user_id,
                XpEvent.source.in_(("room_complete", "hacking_room_complete")),
            )
        )
    )
    return bool((await db.execute(stmt)).scalar())


async def _pred_streak_7(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True when the user's current streak is at least 7 days."""

    result = await streak_service.compute_streak(
        db, user_id=user_id, auto_apply_freezes=False
    )
    return result.streak_days >= 7


async def _pred_streak_30(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True when the user's current streak is at least 30 days."""

    result = await streak_service.compute_streak(
        db, user_id=user_id, auto_apply_freezes=False
    )
    return result.streak_days >= 30


async def _pred_xp_100(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True when the user's lifetime XP is at least 100."""

    total = await xp_service.get_user_xp_total(db, user_id=user_id)
    return total >= 100


async def _pred_xp_1000(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True when the user's lifetime XP is at least 1000."""

    total = await xp_service.get_user_xp_total(db, user_id=user_id)
    return total >= 1000


async def _pred_track_room_complete(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    track_substring: str,
) -> bool:
    """Generic helper: True iff user has completed any room in a track
    whose ``track_id`` contains ``track_substring`` (case-insensitive).

    Single SQL — joins ``xp_events`` (source ``room_complete``) →
    ``path_rooms`` (via ``source_id`` = ``path_rooms.id``) →
    ``learning_paths``.
    """

    needle = f"%{track_substring.lower()}%"
    stmt = select(
        exists().where(
            and_(
                XpEvent.user_id == user_id,
                XpEvent.source.in_(("room_complete", "hacking_room_complete")),
                XpEvent.source_id == PathRoom.id,
                PathRoom.path_id == LearningPath.id,
                LearningPath.track_id.ilike(needle),
            )
        )
    )
    return bool((await db.execute(stmt)).scalar())


async def _pred_python_fluent(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True after completing any Python-track room."""

    return await _pred_track_room_complete(
        db, user_id=user_id, track_substring="python"
    )


async def _pred_hacker_novice(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True after completing any Hacking-track room."""

    return await _pred_track_room_complete(
        db, user_id=user_id, track_substring="hacking"
    )


async def _pred_no_hint(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True after the user got a card right with zero hints.

    Reads ``xp_events.metadata_json`` rows of source ``practice_result``
    and looks for any whose metadata records ``hints_used == 0`` AND
    ``correctness >= 1.0``. Bundle B's ``award_card_xp`` stores both
    fields, so this badge is reachable on real card answers.

    Defensive: rows without metadata (legacy / manual grants) do not
    qualify. The predicate fast-paths True on the first hit.
    """

    stmt = select(XpEvent.metadata_json).where(
        and_(
            XpEvent.user_id == user_id,
            XpEvent.source == "practice_result",
        )
    )
    rows = (await db.execute(stmt)).scalars().all()
    for meta in rows:
        if not isinstance(meta, dict):
            continue
        hints_used = meta.get("hints_used")
        correctness = meta.get("correctness")
        # Both fields must be present and the answer must be fully
        # correct with zero hints. Coerce defensively — the JSON
        # round-trip can return ints as floats and vice versa.
        try:
            if int(hints_used) == 0 and float(correctness) >= 1.0:
                return True
        except (TypeError, ValueError):
            continue
    return False


async def _pred_comeback(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """True when the user has a 3+ day gap in their XP timeline that was
    resolved with a recent (within 7 days) event.

    Strategy: pull every distinct UTC date the user has a positive XP
    event on, sort them, and walk pairs looking for a ``(prev, curr)``
    where ``curr - prev > 3 days`` AND ``curr`` is within the last 7
    days of ``utcnow``. The walk fast-paths True on the first match.

    Cheap: one SELECT, then in-memory scan over O(N) distinct days.
    For an active user with a year of history that's ~365 ints — well
    inside the request budget.
    """

    stmt = (
        select(XpEvent.earned_at)
        .where(
            and_(
                XpEvent.user_id == user_id,
                XpEvent.amount > 0,
            )
        )
        .order_by(XpEvent.earned_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    if len(rows) < 2:
        return False

    today = utcnow().date()
    seven_days_ago = today - timedelta(days=7)
    distinct_days = sorted({as_utc(r).date() for r in rows if r is not None})
    for prev, curr in zip(distinct_days, distinct_days[1:]):
        gap = (curr - prev).days
        # Strictly greater than 3 — a 4+ day jump after a 3-day silence.
        # The ``>= seven_days_ago`` check ensures the comeback is
        # *recent*; old gaps don't keep firing the badge forever.
        if gap > 3 and curr >= seven_days_ago:
            return True
    return False


# ── Catalog ─────────────────────────────────────────────────────────


# Exact 10-badge canonical list per Bundle C spec A.2.
# Order is: foundational (first card / first room), engagement
# (streaks), accumulation (XP totals), track-specific, behavioural.
CATALOG: tuple[BadgeDef, ...] = (
    BadgeDef(
        key="first_card",
        title="First card",
        description="Answered your first practice card.",
        hint="Answer one card to unlock.",
        predicate=_pred_first_card,
    ),
    BadgeDef(
        key="first_room_completed",
        title="First mission",
        description="Completed your first mission.",
        hint="Finish all tasks in a single mission.",
        predicate=_pred_first_room,
    ),
    BadgeDef(
        key="7_day_streak",
        title="Week streak",
        description="Kept a 7-day streak.",
        hint="Practice 7 days in a row.",
        predicate=_pred_streak_7,
    ),
    BadgeDef(
        key="30_day_streak",
        title="Month streak",
        description="Kept a 30-day streak.",
        hint="Practice 30 days in a row.",
        predicate=_pred_streak_30,
    ),
    BadgeDef(
        key="100_xp",
        title="100 XP",
        description="Earned 100 XP.",
        hint="Stack 100 XP from any source.",
        predicate=_pred_xp_100,
    ),
    BadgeDef(
        key="1000_xp",
        title="1000 XP",
        description="Earned 1000 XP.",
        hint="Stack 1000 XP from any source.",
        predicate=_pred_xp_1000,
    ),
    BadgeDef(
        key="python_fluent",
        title="Python fluent",
        description="Completed any Python track room.",
        hint="Finish a mission inside a Python track.",
        predicate=_pred_python_fluent,
    ),
    BadgeDef(
        key="hacker_novice",
        title="Hacker novice",
        description="Completed any Hacking track room.",
        hint="Finish a mission inside a Hacking track.",
        predicate=_pred_hacker_novice,
    ),
    BadgeDef(
        key="no_hint_hero",
        title="No-hint hero",
        description="Got a card right with zero hints.",
        hint="Answer a card correctly without revealing hints.",
        predicate=_pred_no_hint,
    ),
    BadgeDef(
        key="comeback_kid",
        title="Comeback kid",
        description="Came back after a gap of 3+ days.",
        hint="Return after a gap and practice again.",
        predicate=_pred_comeback,
    ),
)


# Index by key so ``award_if_eligible`` can look up the predicate
# without a linear scan. Built once at import time.
_CATALOG_BY_KEY: dict[str, BadgeDef] = {b.key: b for b in CATALOG}


# ── Public API ──────────────────────────────────────────────────────


def catalog() -> tuple[BadgeDef, ...]:
    """Return the canonical ``CATALOG`` tuple. Pure, no I/O."""

    return CATALOG


async def evaluate_all(db: AsyncSession, *, user_id: uuid.UUID) -> dict[str, bool]:
    """Run every predicate in :data:`CATALOG`. Return ``key -> eligible``.

    Used by :func:`award_all_eligible` and surfaceable to the router
    when the client wants the "what's about to unlock" preview without
    persisting anything.
    """

    out: dict[str, bool] = {}
    for badge in CATALOG:
        try:
            out[badge.key] = bool(await badge.predicate(db, user_id=user_id))
        except Exception as exc:  # noqa: BLE001 — never fail caller
            # A bug in one predicate must not poison the rest of the
            # evaluation. Log and treat the badge as not-eligible.
            _log.warning(
                "badge_service: predicate %s raised; treating as False "
                "user_id=%s err=%s",
                badge.key,
                user_id,
                exc,
            )
            out[badge.key] = False
    return out


async def list_unlocked(db: AsyncSession, *, user_id: uuid.UUID) -> list[UserBadge]:
    """Return all ``user_badges`` rows for the user. Newest unlock first.

    Order: ``unlocked_at DESC`` so a freshly-unlocked badge floats to
    the top of the dashboard shelf without the frontend re-sorting.
    """

    stmt = (
        select(UserBadge)
        .where(UserBadge.user_id == user_id)
        .order_by(UserBadge.unlocked_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)


async def _existing_unlock(
    db: AsyncSession, *, user_id: uuid.UUID, badge_key: str
) -> Optional[UserBadge]:
    """Return the row for ``(user_id, badge_key)`` or None."""

    stmt = select(UserBadge).where(
        and_(UserBadge.user_id == user_id, UserBadge.badge_key == badge_key)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def award_if_eligible(
    db: AsyncSession, *, user_id: uuid.UUID, badge_key: str
) -> Optional[UserBadge]:
    """Insert a ``user_badges`` row when the predicate is True.

    Returns:

    * Newly-inserted ``UserBadge`` when the predicate fires AND the
      badge was not previously unlocked.
    * Existing ``UserBadge`` when the badge is already unlocked
      (idempotent — repeated calls don't duplicate, and the caller
      can use the row's ``unlocked_at`` to detect "not new").
    * ``None`` when the predicate is False or the badge_key is not in
      the catalog.

    Race-safety: a concurrent call that wins the unique-constraint
    coin flip will surface ``IntegrityError`` on this call. We catch
    that, roll back the savepoint, and re-fetch the existing row so
    the caller still gets a well-formed return value.
    """

    badge = _CATALOG_BY_KEY.get(badge_key)
    if badge is None:
        return None

    # Predicate gate first — cheaper than a round-trip to insert and
    # roll back on the unique-constraint check.
    eligible = await badge.predicate(db, user_id=user_id)
    if not eligible:
        return None

    # Already unlocked? Short-circuit without an insert attempt.
    existing = await _existing_unlock(db, user_id=user_id, badge_key=badge_key)
    if existing is not None:
        return existing

    row = UserBadge(
        user_id=user_id,
        badge_key=badge_key,
        unlocked_at=datetime.now(timezone.utc),
        metadata_json=None,
    )
    try:
        async with db.begin_nested():
            db.add(row)
        await db.flush()
        return row
    except IntegrityError as exc:
        # Race with another awarder — re-fetch the winner row.
        _log.info(
            "badge_service: race on (%s, %s) — re-fetching existing row err=%s",
            user_id,
            badge_key,
            exc.orig if hasattr(exc, "orig") else exc,
        )
        return await _existing_unlock(db, user_id=user_id, badge_key=badge_key)


async def award_all_eligible(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[UserBadge]:
    """Run every predicate, award newly-eligible badges. Return new rows.

    "New" = inserted by this call. Already-unlocked badges are not
    surfaced. Caller can use the returned list to drive unlock toasts:
    one-card-just-answered → one-or-two badges fire → toast each one.
    """

    eligibility = await evaluate_all(db, user_id=user_id)
    # Pre-fetch all existing unlocks in one query so we can decide
    # "new vs old" without a second round-trip per eligible badge.
    existing_rows = await list_unlocked(db, user_id=user_id)
    existing_keys = {row.badge_key for row in existing_rows}

    newly_inserted: list[UserBadge] = []
    for key, ok in eligibility.items():
        if not ok or key in existing_keys:
            continue
        row = await award_if_eligible(db, user_id=user_id, badge_key=key)
        # ``award_if_eligible`` returns either a fresh row (insert
        # success) or a pre-existing row (race). The pre-fetch above
        # ruled out pre-existing, so any non-None row here is new.
        if row is not None:
            newly_inserted.append(row)
    return newly_inserted


__all__ = [
    "BadgeDef",
    "CATALOG",
    "Predicate",
    "award_all_eligible",
    "award_if_eligible",
    "catalog",
    "evaluate_all",
    "list_unlocked",
]
