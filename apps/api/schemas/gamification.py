"""Gamification wire-shape schemas — Phase 16c Story 1 (Dashboard glance).

These pydantic models pin the public API surface for
``GET /api/gamification/dashboard``. Keeping them in :mod:`schemas` (and
not inline in the router) lets the frontend codegen and the tests share
one canonical definition of every field.

Design notes
------------

* ``HeatmapTile.date`` is a real :class:`datetime.date` (not a string)
  so pydantic emits ISO ``YYYY-MM-DD`` automatically and the test suite
  can assert on date arithmetic without re-parsing strings.
* ``heatmap`` is a **dense** 365-element list (one entry per day,
  today inclusive — Phase 16c Bundle B spec line 148). Days with no
  XP carry ``xp=0``. The dense layout simplifies the React heatmap
  grid (it iterates a fixed-length array without filling gaps) and
  makes the payload size deterministic across users.
* ``ActivePathSummary.path_id`` is the canonical path UUID — frontend
  links to ``/paths/{slug}`` but uses ``path_id`` as the React key.
* ``level_tier`` (e.g. ``"Silver II"``) and ``level_name`` (e.g.
  ``"Silver"``) are surfaced separately so the UI can render the badge
  icon (driven by ``level_name``) independent of the sub-tier label.
* ``xp_to_next_level`` is the integer XP delta from the user's current
  total to the lower bound of the next tier band (Bronze→Silver=500,
  Silver→Gold=2000, Gold→Platinum=5000, Platinum→Diamond=10000). The
  open-ended Diamond band returns ``0`` because there is no next tier.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HeatmapTile(BaseModel):
    """One day on the 365-tile activity heatmap.

    Dense representation — every day in the trailing 365-day window
    ships exactly one tile, with ``xp=0`` on quiet days. Phase 16c
    Bundle B spec line 148 ("exactly 365 day rows, today inclusive").
    """

    model_config = ConfigDict(frozen=True)

    date: date
    xp: int = Field(..., ge=0)


class ActivePathSummary(BaseModel):
    """One row of the dashboard's "Active paths" widget.

    A path counts as "active" when the user has at least one
    ``PracticeResult`` against any task inside any of the path's rooms.
    The router caps the list at the 5 most-recent (by latest answer
    timestamp) so the dashboard never balloons for a power user.
    """

    model_config = ConfigDict(frozen=True)

    path_id: UUID
    slug: str
    title: str
    rooms_total: int = Field(..., ge=0)
    rooms_completed: int = Field(..., ge=0)


class GamificationDashboard(BaseModel):
    """Top-level payload for ``GET /api/gamification/dashboard``.

    Always returns 200. New accounts come back with all zeros, an empty
    ``heatmap`` list, and an empty ``active_paths`` list — the frontend
    treats absence as "fresh start" and shows the onboarding nudge.

    Field order mirrors the Story 1 acceptance dump so a diff against
    the spec is one column wide.
    """

    model_config = ConfigDict(frozen=True)

    xp_total: int = Field(..., ge=0)
    level_tier: str
    level_name: str
    level_progress_pct: int = Field(..., ge=0, le=100)
    xp_to_next_level: int = Field(..., ge=0)
    streak_days: int = Field(..., ge=0)
    streak_freezes_left: int = Field(..., ge=0)
    daily_goal_xp: int = Field(..., ge=0)
    daily_xp_earned: int = Field(..., ge=0)
    heatmap: list[HeatmapTile]
    active_paths: list[ActivePathSummary]


class BadgeOut(BaseModel):
    """One badge entry on the badges endpoint.

    The same shape covers both unlocked and locked badges — the
    ``unlocked`` flag and presence/absence of ``unlocked_at`` discriminate.
    Bundle C router renders the locked subset by reading ``hint`` (the
    "how to get it" copy) and the unlocked subset by reading
    ``unlocked_at``. Keeping a single shape avoids a second pydantic
    model and makes it cheap for the frontend to render the two lists
    with the same component.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    title: str
    description: str
    # Always present — the frontend may render hints even on unlocked
    # badges (e.g. tooltip "you got this by..."), and an Optional here
    # would make every consumer null-check.
    hint: str
    unlocked: bool
    unlocked_at: Optional[datetime] = None


class BadgesResponse(BaseModel):
    """Top-level payload for ``GET /api/gamification/badges``.

    Two parallel arrays keep the wire shape simple: the frontend
    iterates ``unlocked`` for the lit-up shelf and ``locked`` for the
    greyed-out tail. The full catalog count is always
    ``len(unlocked) + len(locked)`` — Bundle C catalog has 10 entries.
    """

    model_config = ConfigDict(frozen=True)

    unlocked: list[BadgeOut]
    locked: list[BadgeOut]


__all__ = [
    "ActivePathSummary",
    "BadgeOut",
    "BadgesResponse",
    "GamificationDashboard",
    "HeatmapTile",
]
