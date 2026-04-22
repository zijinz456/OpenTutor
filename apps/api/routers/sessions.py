"""ADHD daily-session endpoints (Phase 13 T2).

Currently exposes a single route — ``GET /api/sessions/daily-plan`` —
used by the :func:`DailySessionCTA` dashboard component to fetch a tiny
curated batch of practice problems for a single ADHD-friendly session.

The mount prefix ``/api/sessions`` is registered in
:mod:`services.router_registry`. The slash-free endpoint path keeps
``/api/sessions/daily-plan`` readable from curl without a trailing
redirect.

The selection logic lives in :mod:`services.daily_plan` — the router
itself is intentionally thin: validate, delegate, return. Auth is handled
by :func:`services.auth.dependency.get_current_user` so the route stays
locked behind the same deployment-mode gate as every other API. In
single-user local mode (the default) that dependency transparently
returns the one local user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from schemas.sessions import DailyPlan, DailySessionSize
from services.auth.dependency import get_current_user
from services.daily_plan import select_daily_plan

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/daily-plan",
    response_model=DailyPlan,
    summary="Get the ADHD daily-session batch",
    description=(
        "Return a curated batch of 1 / 5 / 10 practice cards prioritised "
        "by FSRS overdue → due today → recently failed, with type "
        "rotation applied inside each tier. Used by the dashboard "
        "daily-session CTA. Any `size` other than 1, 5, or 10 is "
        "rejected with HTTP 422. When the pool is empty the response is "
        "`{cards: [], size: 0, reason: \"nothing_due\"}` so the UI can "
        "render the quick-closure screen without a special case."
    ),
)
async def get_daily_plan(
    size: int = Query(
        ...,
        description="Session size in cards. Must be 1, 5, or 10.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DailyPlan:
    # Validate after Query coercion so query-string '5' → int 5 works.
    if size not in (1, 5, 10):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"size must be 1, 5, or 10 (got {size})")
    _: DailySessionSize = size  # type-check only
    """Return the configured user's next daily-session batch.

    The ``user`` parameter is accepted purely to keep the auth dependency
    wired in and to match the convention every other API router follows
    (single-user mode still requires ``get_current_user`` to resolve the
    lone local user). The card selection itself is global because all
    practice problems belong to that single user — see
    :mod:`services.daily_plan` for the rationale.
    """

    _ = user  # present for auth gate, unused under single-user selection
    return await select_daily_plan(db, size)


__all__ = ["router"]
