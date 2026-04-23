"""Brutal Drill card selector (Phase 6 T1).

Thin wrapper over :func:`services.daily_plan.select_daily_plan` with
``strategy="struggle_first"``. Exists for two reasons:

1. **Warning contract.** The daily endpoint treats a partial fill as a
   happy path — the ADHD UI happily renders a short deck with no
   visible signal. The brutal endpoint MUST surface partial fills
   because a user who asked for a 50-card session is specifically
   opting into a heavy drill; silently handing them 12 cards would
   betray that intent. This wrapper translates ``len(cards) < size``
   into an explicit ``warning="pool_small"``.

2. **Router ergonomics.** Keeping the selector thin keeps the router
   trivial — it can import one function and not care about the dual
   ``(plan, warning)`` bookkeeping. Moving the warning logic into the
   daily module would either pollute its return shape (which Phase 13
   tests pin) or require a second exit path on the daily router.

The wrapper itself does no DB work; all validation and selection lives
behind ``select_daily_plan``. That includes the size guard
(``ALLOWED_BRUTAL_SIZES``) — non-HTTP callers that pass an invalid size
get the same :class:`ValueError` the daily path raises.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.sessions import DailyPlan
from services.daily_plan import select_daily_plan

BrutalWarning = Literal["pool_small"]
"""The only warning the brutal selector surfaces. Narrowed to a
``Literal`` so FastAPI's response model and our type-check gate stay in
lockstep with :class:`schemas.sessions.BrutalPlanResponse`."""


async def select_brutal_plan(
    db: AsyncSession,
    size: int,
) -> tuple[DailyPlan, str | None]:
    """Return the brutal-session batch plus a partial-fill warning.

    Args:
        db: Active async SQLAlchemy session. Passed through to
            :func:`select_daily_plan` — the caller owns the
            transaction.
        size: Requested batch size. Must be one of
            :data:`services.daily_plan.ALLOWED_BRUTAL_SIZES`; any other
            value raises :class:`ValueError` from the underlying
            selector.

    Returns:
        Tuple ``(plan, warning)``:

        * ``plan`` — a :class:`schemas.sessions.DailyPlan` produced by
          the struggle-first selector. Its ``reason`` may be
          ``"nothing_due"`` when the DB is genuinely empty.
        * ``warning`` — ``"pool_small"`` when the curated pool was
          smaller than ``size`` (partial fill), ``None`` otherwise.
          Crucially, an empty pool (``reason="nothing_due"``) is NOT
          reported as ``"pool_small"`` — the frontend distinguishes
          the two states because empty means "nothing to drill" while
          partial means "we found some but fewer than you wanted".

    Note:
        We do not expose a ``user_id`` parameter. Card selection in
        this codebase is global under single-user local mode — see
        ``services.daily_plan`` module docstring for the rationale.
    """

    plan = await select_daily_plan(db, size=size, strategy="struggle_first")

    # Distinguish "empty pool" from "partial fill": the former is the
    # nothing_due signal the frontend already knows how to render, the
    # latter is the brutal-specific pool_small warning.
    if plan.reason == "nothing_due":
        return plan, None

    warning: str | None = "pool_small" if len(plan.cards) < size else None
    return plan, warning


__all__ = ["select_brutal_plan"]
