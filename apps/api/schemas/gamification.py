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
* ``heatmap`` is **sparse** — only days where the user actually earned
  XP show up. The 365-tile layout is the frontend's job (it fills any
  missing day with 0 XP). This keeps the payload small for new accounts
  (length 0) and avoids shipping 364 empty objects on a fresh DB.
* ``ActivePathSummary.path_id`` is the canonical path UUID — frontend
  links to ``/paths/{slug}`` but uses ``path_id`` as the React key.
* ``level_tier`` (e.g. ``"Silver II"``) and ``level_name`` (e.g.
  ``"Silver"``) are surfaced separately so the UI can render the badge
  icon (driven by ``level_name``) independent of the sub-tier label.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HeatmapTile(BaseModel):
    """One non-empty day on the 365-tile activity heatmap.

    Sparse representation — only days with ``xp > 0`` ship. Frontend
    fills missing days with empty pale tiles. Story 1 AC #2 codifies
    this contract.
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
    streak_days: int = Field(..., ge=0)
    streak_freezes_left: int = Field(..., ge=0)
    daily_goal_xp: int = Field(..., ge=0)
    daily_xp_earned: int = Field(..., ge=0)
    heatmap: list[HeatmapTile]
    active_paths: list[ActivePathSummary]


__all__ = [
    "ActivePathSummary",
    "GamificationDashboard",
    "HeatmapTile",
]
