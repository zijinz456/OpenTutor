"""Gamification router — Phase 16c Story 1 (Dashboard glance).

Mounts :data:`router` on ``/api/gamification``. The single P0 endpoint is
``GET /api/gamification/dashboard`` which returns one
:class:`schemas.gamification.GamificationDashboard` payload combining
five upstream sources:

* :mod:`services.xp_service` — XP total, tier label, level progress,
  per-day heatmap aggregation. Owned by Subagent A.
* :mod:`services.streak_service` — current streak, side-effect-free.
* :mod:`services.freeze` — remaining weekly freeze budget.
* :mod:`models.preference.UserPreference` — daily-goal-XP override
  (defaults to 10 when no row exists).
* :mod:`models.learning_path.LearningPath` + :mod:`models.practice` —
  active-paths summary cap-5 by latest activity.

Always returns 200. New accounts get all-zero numbers + empty arrays
(Story 1 AC #1). The router does no DB write; the
``compute_streak`` call is invoked with ``auto_apply_freezes=False`` so
dashboard polls cannot accidentally consume the user's freeze budget.

Registration: this router is NOT mounted by ``services.router_registry``
yet — the main agent owns that wiring as part of Bundle A integration.
The module exports ``router`` (one global) so the registration is a
one-line ``include_router`` whenever it lands.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import date as date_cls
from datetime import datetime, time, timedelta, timezone
from typing import Iterable

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from libs.datetime_utils import as_utc, utcnow
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem, PracticeResult
from models.preference import UserPreference
from models.user import User
from schemas.gamification import (
    ActivePathSummary,
    BadgeOut,
    BadgesResponse,
    GamificationDashboard,
    HeatmapTile,
)
from services import freeze as freeze_service
from services import streak_service, xp_service
from services.auth.dependency import get_current_user
from services.gamification import badge_service

logger = logging.getLogger(__name__)

# Subagent A's daily-goal preference key. Plain string so the
# preference cascade can resolve it without a schema change.
_DAILY_GOAL_DIMENSION: str = "daily_goal_xp"
_DAILY_GOAL_DEFAULT: int = 10

# Story 1: heatmap covers exactly 365 days inclusive of today.
_HEATMAP_WINDOW_DAYS: int = 365

# Story 1 AC: cap dashboard's active-paths list at 5 most-recent.
_ACTIVE_PATHS_CAP: int = 5

# Lower bound of each tier band — mirrors ``services.xp_service.LEVEL_BANDS``
# (Bronze 0, Silver 500, Gold 2000, Platinum 5000, Diamond 10000). Kept
# inline (not imported) so this router does not depend on the private
# ``LEVEL_BANDS`` symbol; the band table changes ~never and a hard-coded
# duplicate is cheaper than an export. The Diamond band is open-ended,
# hence the trailing ``None`` — there is no next tier to reach.
_NEXT_BAND_THRESHOLDS: tuple[int, ...] = (500, 2000, 5000, 10000)


def _xp_to_next_level(xp_total: int) -> int:
    """Return XP needed to reach the next tier's lower bound.

    Spec (Phase 16c Bundle B Part A line 142): ``xp_to_next_level``.
    Bronze (0..499)  → 500 - xp
    Silver (500..1999) → 2000 - xp
    Gold (2000..4999)  → 5000 - xp
    Platinum (5000..9999) → 10000 - xp
    Diamond (10000+) → 0 (no next band)

    Negative ``xp_total`` is clamped to 0 (defensive against any
    upstream subtraction overshoot, mirroring ``xp_service``).
    """

    xp = max(0, xp_total)
    for threshold in _NEXT_BAND_THRESHOLDS:
        if xp < threshold:
            return threshold - xp
    return 0


router = APIRouter(prefix="/api/gamification", tags=["gamification"])


async def _resolve_daily_goal_xp(db: AsyncSession, user: User) -> int:
    """Return the user's configured daily-goal XP, defaulting to 10.

    Per Story 1 AC #5 the goal is configurable per-user. The repo
    stores user-scoped settings as ``UserPreference`` rows keyed by
    ``dimension`` rather than a JSON blob on ``users.preferences``,
    so this helper looks up the most-specific row (``scope='global'``,
    no scene, no course) and parses its ``value`` as int. Any parse
    failure or absent row falls back to 10 — surfacing a goal of 0
    would render a "0 / 0 XP" widget that breaks the daily-goal-ring
    component on the frontend.
    """

    stmt = (
        select(UserPreference.value)
        .where(
            UserPreference.user_id == user.id,
            UserPreference.dimension == _DAILY_GOAL_DIMENSION,
            UserPreference.dismissed_at.is_(None),
        )
        .order_by(UserPreference.updated_at.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if row is None or row[0] is None:
        return _DAILY_GOAL_DEFAULT
    try:
        parsed = int(str(row[0]).strip())
    except (TypeError, ValueError):
        logger.warning(
            "user %s has non-int daily_goal_xp preference %r; falling back to %d",
            user.id,
            row[0],
            _DAILY_GOAL_DEFAULT,
        )
        return _DAILY_GOAL_DEFAULT
    # A zero / negative goal is nonsensical; clamp to default rather
    # than 200% the goal-ring forever. Negative values shouldn't get
    # past the preference write path, but defending here is cheap.
    return parsed if parsed > 0 else _DAILY_GOAL_DEFAULT


def _aggregate_heatmap(
    events: Iterable[object], *, today: date_cls
) -> list[HeatmapTile]:
    """Build a dense 365-day heatmap ending at ``today`` (inclusive).

    Spec (Phase 16c Bundle B line 148): "exactly 365 day rows, today
    inclusive". Days with no XP carry ``xp=0``; days with multiple
    events get summed. Result is ordered oldest → newest so the
    frontend grid iterates left-to-right with no extra sort.

    ``today`` is injected (rather than re-read from the clock) so the
    caller controls the UTC reference and tests are deterministic.
    """

    bucket: dict[date_cls, int] = {}
    for event in events:
        amount = getattr(event, "amount", 0) or 0
        if amount <= 0:
            continue
        earned_at = getattr(event, "earned_at", None)
        if earned_at is None:
            continue
        day = as_utc(earned_at).date()
        bucket[day] = bucket.get(day, 0) + int(amount)

    # Walk the 365-day window from oldest to today (inclusive), filling
    # zero-XP tiles for quiet days. ``range(364, -1, -1)`` yields 364
    # down to 0, so ``today - timedelta(days=364)`` is the first tile
    # and ``today`` is the last — exactly 365 entries.
    tiles: list[HeatmapTile] = []
    for offset in range(_HEATMAP_WINDOW_DAYS - 1, -1, -1):
        day = today - timedelta(days=offset)
        tiles.append(HeatmapTile(date=day, xp=bucket.get(day, 0)))
    return tiles


@dataclass
class _PathBucket:
    """Per-path aggregation state used while building the active-paths list.

    Carrying ``rooms_touched`` as a typed ``set[uuid.UUID]`` (instead of
    a dict-of-objects) keeps the static type checker happy on the
    ``set.update`` and iteration call sites in ``_build_active_paths``.
    """

    latest: datetime | None
    rooms_touched: set[uuid.UUID] = field(default_factory=set)


async def _build_active_paths(
    db: AsyncSession, *, user_id: uuid.UUID
) -> list[ActivePathSummary]:
    """Return up to 5 paths the user has touched, newest activity first.

    "Touched" = at least one ``PracticeResult`` row referencing a task
    inside any room of the path. ``rooms_completed`` is the number of
    rooms whose every task has a positive answer for this user
    (matches the ``room_complete`` definition used in
    :mod:`routers.paths`). If a user has zero practice history the
    list is empty — the dashboard frontend treats that as "no active
    work yet" without further branching.
    """

    # 1) Find every (path_id, room_id, latest_answered_at) tuple the
    #    user has touched. Single round-trip via PracticeResult ⨝
    #    PracticeProblem ⨝ PathRoom.
    activity_stmt = (
        select(
            PathRoom.path_id,
            PathRoom.id.label("room_id"),
            func.max(PracticeResult.answered_at).label("latest"),
        )
        .join(PracticeProblem, PracticeProblem.id == PracticeResult.problem_id)
        .join(PathRoom, PathRoom.id == PracticeProblem.path_room_id)
        .where(PracticeResult.user_id == user_id)
        .group_by(PathRoom.path_id, PathRoom.id)
    )
    rows = (await db.execute(activity_stmt)).all()
    if not rows:
        return []

    by_path: dict[uuid.UUID, _PathBucket] = {}
    for path_id, room_id, latest in rows:
        latest_dt = as_utc(latest) if isinstance(latest, datetime) else None
        bucket = by_path.setdefault(path_id, _PathBucket(latest=latest_dt))
        # Track the freshest activity across all rooms in the path.
        if latest_dt is not None:
            if bucket.latest is None or latest_dt > bucket.latest:
                bucket.latest = latest_dt
        bucket.rooms_touched.add(room_id)

    # 2) For every touched path, count total rooms (not only touched
    #    ones) so the "X / Y rooms" caption is accurate.
    path_ids = list(by_path.keys())
    paths_stmt = select(LearningPath).where(LearningPath.id.in_(path_ids))
    paths = list((await db.execute(paths_stmt)).scalars().all())

    rooms_total_stmt = (
        select(PathRoom.path_id, func.count(PathRoom.id))
        .where(PathRoom.path_id.in_(path_ids))
        .group_by(PathRoom.path_id)
    )
    rooms_total = {pid: int(c) for pid, c in (await db.execute(rooms_total_stmt)).all()}

    # 3) Per-touched-room completion count: a room is "completed" when
    #    every one of its tasks has at least one correct answer for
    #    this user. We fan out one batched query rather than per-room
    #    round-trips; the result keys both "task_total" and
    #    "task_correct" by room_id.
    touched_room_ids: set[uuid.UUID] = set()
    for bucket in by_path.values():
        touched_room_ids.update(bucket.rooms_touched)

    task_totals_stmt = (
        select(PracticeProblem.path_room_id, func.count(PracticeProblem.id))
        .where(PracticeProblem.path_room_id.in_(touched_room_ids))
        .group_by(PracticeProblem.path_room_id)
    )
    task_totals = {rid: int(c) for rid, c in (await db.execute(task_totals_stmt)).all()}

    correct_stmt = (
        select(
            PracticeProblem.path_room_id,
            func.count(func.distinct(PracticeProblem.id)),
        )
        .join(PracticeResult, PracticeResult.problem_id == PracticeProblem.id)
        .where(
            PracticeProblem.path_room_id.in_(touched_room_ids),
            PracticeResult.user_id == user_id,
            PracticeResult.is_correct.is_(True),
        )
        .group_by(PracticeProblem.path_room_id)
    )
    correct_counts = {rid: int(c) for rid, c in (await db.execute(correct_stmt)).all()}

    # 4) Assemble summaries.
    summaries: list[tuple[ActivePathSummary, datetime | None]] = []
    paths_by_id = {p.id: p for p in paths}
    for path_id, bucket in by_path.items():
        path = paths_by_id.get(path_id)
        if path is None:
            # Race: the user touched a path that was deleted. Skip
            # silently — surfacing it would just confuse the dashboard.
            continue
        rooms_touched = bucket.rooms_touched
        completed = sum(
            1
            for rid in rooms_touched
            if task_totals.get(rid, 0) > 0
            and correct_counts.get(rid, 0) >= task_totals.get(rid, 0)
        )
        summary = ActivePathSummary(
            path_id=path.id,
            slug=path.slug,
            title=path.title,
            rooms_total=rooms_total.get(path.id, 0),
            rooms_completed=completed,
        )
        summaries.append((summary, bucket.latest))

    # Sort by latest activity DESC; missing timestamps go last.
    summaries.sort(
        key=lambda pair: pair[1] or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return [s for s, _ in summaries[:_ACTIVE_PATHS_CAP]]


@router.get(
    "/dashboard",
    response_model=GamificationDashboard,
    summary="Aggregated gamification dashboard payload",
    description=(
        "Returns the XP / streak / heatmap / active-paths snapshot used "
        "by the dashboard's gamification panel. Always 200 — a new "
        "account comes back with all zeros and empty arrays."
    ),
)
async def get_dashboard(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GamificationDashboard:
    """Compose the dashboard payload from XP, streak, freeze, and path data."""

    # ── XP totals + tier ────────────────────────────────────────────
    xp_total = int(await xp_service.get_user_xp_total(db, user_id=user.id))
    tier_label = xp_service.tier_name(xp_total)
    # ``tier_label`` is "Silver II"-style; the bare tier name is the
    # space-separated head ("Silver"). Frontend uses that to pick the
    # rank icon without parsing the full label.
    level_name = tier_label.split(" ", 1)[0] if tier_label else ""
    level_progress_pct = int(xp_service.level_progress_pct(xp_total))

    # ── Streak (read-only — no auto-apply on every dashboard hit) ──
    streak_result = await streak_service.compute_streak(
        db,
        user_id=user.id,
        auto_apply_freezes=False,
    )

    # ── Freeze budget (post-streak, redundant with streak_result but
    # explicit for clarity if streak short-circuits before the meta
    # call). ──
    freezes_left = streak_result.freezes_left_this_week

    # ── Daily goal vs daily earned ──────────────────────────────────
    daily_goal = await _resolve_daily_goal_xp(db, user)

    today = utcnow().date()
    today_start = datetime.combine(today, time.min, tzinfo=timezone.utc)
    today_end = today_start + timedelta(days=1)
    today_events = await xp_service.get_xp_events_in_range(
        db, user_id=user.id, start_utc=today_start, end_utc=today_end
    )
    daily_earned = sum(max(0, int(getattr(e, "amount", 0) or 0)) for e in today_events)

    # ── 365-day heatmap ─────────────────────────────────────────────
    window_start = today - timedelta(days=_HEATMAP_WINDOW_DAYS - 1)
    heatmap_start_dt = datetime.combine(window_start, time.min, tzinfo=timezone.utc)
    heatmap_end_dt = today_end  # exclusive end already at today + 1
    heatmap_events = await xp_service.get_xp_events_in_range(
        db, user_id=user.id, start_utc=heatmap_start_dt, end_utc=heatmap_end_dt
    )
    heatmap = _aggregate_heatmap(heatmap_events, today=today)

    # ── Active paths ────────────────────────────────────────────────
    active_paths = await _build_active_paths(db, user_id=user.id)

    # Sanity: ``can_freeze`` returns the live count even when no
    # streak compute happened — defend against future refactors that
    # short-circuit ``compute_streak`` before computing the meta.
    if freezes_left is None:
        _, meta = await freeze_service.can_freeze(db, user.id)
        freezes_left = int(meta["remaining"])

    return GamificationDashboard(
        xp_total=xp_total,
        level_tier=tier_label,
        level_name=level_name,
        level_progress_pct=level_progress_pct,
        xp_to_next_level=_xp_to_next_level(xp_total),
        streak_days=streak_result.streak_days,
        streak_freezes_left=freezes_left,
        daily_goal_xp=daily_goal,
        daily_xp_earned=daily_earned,
        heatmap=heatmap,
        active_paths=active_paths,
    )


@router.get(
    "/badges",
    response_model=BadgesResponse,
    summary="Badge catalog with per-user unlock state",
    description=(
        "Returns the full Bundle C badge catalog split into "
        "``unlocked`` (with ``unlocked_at`` timestamps) and ``locked`` "
        "(with hint copy for the locked-state UI). Always 200 — a new "
        "account comes back with all ten badges in ``locked``. The "
        "service awards happen elsewhere (quiz_submission, "
        "room_completion); this endpoint is read-only."
    ),
)
async def get_badges(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BadgesResponse:
    """Compose the badges payload from the catalog and the user's unlocks.

    Implementation notes:

    * Order of ``unlocked`` mirrors the service's
      ``ORDER BY unlocked_at DESC`` — newest unlock first so the shelf
      surfaces fresh wins prominently.
    * Order of ``locked`` mirrors :data:`badge_service.CATALOG`
      definition order — the canonical "introduce easy badges first"
      order from the Bundle C spec. The frontend can re-sort if it
      wants alphabetical / progress-based ordering.
    """

    unlocked_rows = await badge_service.list_unlocked(db, user_id=user.id)
    unlocked_map = {row.badge_key: row for row in unlocked_rows}
    catalog = badge_service.catalog()

    unlocked: list[BadgeOut] = []
    locked: list[BadgeOut] = []

    # First pass: build the unlocked list in service order
    # (``unlocked_at DESC``). Iterate the rows themselves so the
    # ordering propagates from the SQL.
    for row in unlocked_rows:
        badge = next((b for b in catalog if b.key == row.badge_key), None)
        if badge is None:
            # Row references a key no longer in the catalog. Skip
            # silently — surfacing it would just confuse the shelf.
            continue
        unlocked.append(
            BadgeOut(
                key=badge.key,
                title=badge.title,
                description=badge.description,
                hint=badge.hint,
                unlocked=True,
                unlocked_at=row.unlocked_at,
            )
        )

    # Second pass: locked badges in catalog order.
    for badge in catalog:
        if badge.key in unlocked_map:
            continue
        locked.append(
            BadgeOut(
                key=badge.key,
                title=badge.title,
                description=badge.description,
                hint=badge.hint,
                unlocked=False,
                unlocked_at=None,
            )
        )

    return BadgesResponse(unlocked=unlocked, locked=locked)


__all__ = ["router"]
