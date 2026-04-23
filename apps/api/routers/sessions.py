"""Session-scoped endpoints.

Hosts both the Phase 13 ADHD daily-session endpoint
(``GET /api/sessions/daily-plan``) and the Phase 6 Brutal Drill
endpoint (``GET /api/sessions/brutal-plan``). Both live on the same
router per the F1 decision in ``plan/brutal_drill_mode_phase6.md``:
they share the ``/api/sessions`` mount, the auth dependency, and the
selection pipeline in :mod:`services.daily_plan` — splitting them into
two routers would triple the wiring for no ownership gain.

The mount prefix ``/api/sessions`` is registered in
:mod:`services.router_registry`. Slash-free endpoint paths keep them
readable from curl without a trailing redirect.

The selection logic lives in :mod:`services.daily_plan` and
:mod:`services.brutal_plan` — this router is intentionally thin:
validate, delegate, return. Auth is handled by
:func:`services.auth.dependency.get_current_user` so every route stays
locked behind the same deployment-mode gate as the rest of the API. In
single-user local mode (the default) that dependency transparently
returns the one local user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from schemas.sessions import (
    BrutalPlanResponse,
    BrutalSessionSize,
    DailyPlan,
    DailySessionSize,
)
from services.auth.dependency import get_current_user
from services.brutal_plan import select_brutal_plan
from services.daily_plan import select_daily_plan
from services.freeze import active_frozen_problem_ids

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
        '`{cards: [], size: 0, reason: "nothing_due"}` so the UI can '
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

        raise HTTPException(
            status_code=422, detail=f"size must be 1, 5, or 10 (got {size})"
        )
    _: DailySessionSize = size  # type-check only
    """Return the configured user's next daily-session batch.

    The ``user`` parameter is accepted purely to keep the auth dependency
    wired in and to match the convention every other API router follows
    (single-user mode still requires ``get_current_user`` to resolve the
    lone local user). The card selection itself is global because all
    practice problems belong to that single user — see
    :mod:`services.daily_plan` for the rationale.
    """

    # Phase 14 T1: honor active freeze tokens. A frozen problem stays
    # hidden from the daily-plan selector for 24h without touching
    # FSRS. ``active_frozen_problem_ids`` returns ``[]`` in the no-tokens
    # case so the pre-Phase-14 path is untouched.
    frozen = await active_frozen_problem_ids(db, user.id)
    return await select_daily_plan(db, size, excluded_ids=frozen)


@router.get(
    "/brutal-plan",
    response_model=BrutalPlanResponse,
    summary="Get the Brutal Drill session batch",
    description=(
        "Return a curated batch of 20 / 30 / 50 MC-only practice cards "
        "prioritised struggle-first: recent-fail (14d window) → overdue "
        "→ due today → never-seen with `concept_slug`. Used by the "
        "Brutal Drill dashboard entry (Phase 6). Any `size` other than "
        "20, 30, or 50 is rejected with HTTP 422. The response includes "
        '`warning="pool_small"` when the pool was non-empty but smaller '
        "than the requested size — the frontend uses that to raise a "
        "toast instead of silently shrinking the deck."
    ),
)
async def get_brutal_plan(
    # Pydantic v2 ``Literal[int]`` does not coerce query strings ("20" →
    # 20) under FastAPI's ``Query`` validator, so ``?size=20`` returns 422
    # with the Literal binding. Accept raw ``int`` at the HTTP edge and
    # enforce the closed set manually — the 422 body shape mirrors what
    # the Literal would have produced.
    size: int = Query(
        30,
        description="Session size in cards. Must be 20, 30, or 50.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BrutalPlanResponse:
    """Return the configured user's next brutal-drill batch.

    The ``user`` parameter is accepted purely to keep the auth
    dependency wired in and to match the convention every other API
    router follows. Selection itself is global under single-user local
    mode — see :mod:`services.daily_plan` for the rationale.
    """

    if size not in (20, 30, 50):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=422,
            detail=f"size must be 20, 30, or 50 (got {size})",
        )
    _: BrutalSessionSize = size  # type: ignore[assignment]  # post-validation alias
    # Phase 14 T1: brutal plan honors freezes too — a card frozen in an
    # ADHD-mode session stays hidden from the struggle-first drill for
    # the same 24h window. Keeps the "❄" invariant across surfaces.
    frozen = await active_frozen_problem_ids(db, user.id)
    plan, warning = await select_brutal_plan(db, size=size, excluded_ids=frozen)
    # ``size`` on the response echoes ``len(cards)`` — not the requested
    # size — so the frontend can render "got 12 of 30" without a second
    # comparison. The explicit ``warning`` covers the semantic signal.
    return BrutalPlanResponse(
        cards=plan.cards,
        size=len(plan.cards),
        warning=warning,  # type: ignore[arg-type]
    )


__all__ = ["router"]
