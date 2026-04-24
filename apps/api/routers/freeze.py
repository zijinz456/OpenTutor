"""Freeze-token HTTP surface — Phase 14 T1 ADHD UX.

Three endpoints under ``/api/freeze``:

* ``POST /api/freeze/{problem_id}`` — freeze a card for 24h.
* ``GET  /api/freeze/status`` — introspect remaining weekly quota +
  currently-active freezes.
* ``DELETE /api/freeze/{problem_id}`` — manual unfreeze (does NOT
  refund the quota, per critic C8).

Shape mirrors the Phase 13 ``/api/sessions/*`` router — thin validate /
delegate / return; all logic lives in :mod:`services.freeze`. Auth is
the shared :func:`services.auth.dependency.get_current_user` gate.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.practice import PracticeProblem
from models.user import User
from services.auth.dependency import get_current_user
from services.freeze import (
    ConflictError,
    freeze_card,
    get_freeze_status,
    unfreeze_card,
)

router = APIRouter()


# ── Response schemas (inline — narrow, not worth a schemas/ module) ─


class FreezeResponse(BaseModel):
    """Return value for ``POST /api/freeze/{problem_id}``.

    Kept flat (``expires_at`` + ``quota_remaining``) so the frontend
    doesn't need a second round-trip to refresh the footer chip —
    freeze button and chip consume the same payload.
    """

    expires_at: str = Field(..., description="ISO-8601 UTC timestamp")
    quota_remaining: int = Field(
        ..., ge=0, description="Freezes left for this ISO week after this write"
    )


class ActiveFreezePayload(BaseModel):
    """One active-freeze row in the status response."""

    problem_id: uuid.UUID
    expires_at: str


class FreezeStatusResponse(BaseModel):
    """Return value for ``GET /api/freeze/status``."""

    quota_remaining: int = Field(..., ge=0)
    weekly_used: int = Field(..., ge=0)
    active_freezes: list[ActiveFreezePayload] = Field(default_factory=list)


# ── Endpoint 1: POST /api/freeze/{problem_id} ───────────────────────


@router.post(
    "/{problem_id}",
    response_model=FreezeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Freeze a practice problem for 24 hours",
    description=(
        "Hides ``problem_id`` from the daily-plan selector for 24h "
        "without touching FSRS state. Weekly cap of three freezes per "
        "UTC ISO week is enforced; per-card lifetime cap of one freeze "
        "per user × problem. Returns 409 when either cap is hit, 404 "
        "when the problem does not exist."
    ),
)
async def post_freeze(
    problem_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FreezeResponse:
    """Create a freeze row; map service errors to the correct HTTP code."""

    # 404 guard — freeze on a non-existent problem would still succeed
    # via the FK (SQLite FK enforcement is off by default) so we check
    # explicitly. Keeps the API contract honest regardless of dialect.
    exists = await db.execute(
        select(PracticeProblem.id).where(PracticeProblem.id == problem_id)
    )
    if exists.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "problem_not_found", "problem_id": str(problem_id)},
        )

    try:
        token = await freeze_card(db, user.id, problem_id)
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": exc.reason, "detail": str(exc)},
        ) from exc

    # After writing, fetch the post-write quota so the frontend footer
    # chip updates without a second call. Re-using get_freeze_status
    # would round-trip one extra query for ``active_freezes`` we don't
    # need here — we compute ``remaining`` off the known post-insert
    # count instead.
    from services.freeze import can_freeze

    _, meta = await can_freeze(db, user.id)

    return FreezeResponse(
        expires_at=token.expires_at.isoformat(),
        quota_remaining=meta["remaining"],
    )


# ── Endpoint 2: GET /api/freeze/status ──────────────────────────────


@router.get(
    "/status",
    response_model=FreezeStatusResponse,
    summary="Inspect remaining weekly freeze quota + active freezes",
    description=(
        "Always 200. When the user has never frozen a card the body is "
        "``{quota_remaining: 3, weekly_used: 0, active_freezes: []}``. "
        "Used by the dashboard footer chip and the card-runner to "
        "decide whether the ❄ button is enabled."
    ),
)
async def get_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FreezeStatusResponse:
    """Return quota + active-freeze payload."""

    payload = await get_freeze_status(db, user.id)
    return FreezeStatusResponse(
        quota_remaining=int(payload["quota_remaining"]),  # type: ignore[arg-type]
        weekly_used=int(payload["weekly_used"]),  # type: ignore[arg-type]
        active_freezes=[
            ActiveFreezePayload(
                problem_id=row["problem_id"],  # type: ignore[index]
                expires_at=row["expires_at"].isoformat(),  # type: ignore[index,union-attr]
            )
            for row in payload["active_freezes"]  # type: ignore[union-attr]
        ],
    )


# ── Endpoint 3: DELETE /api/freeze/{problem_id} ─────────────────────


@router.delete(
    "/{problem_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unfreeze a card (does NOT refund weekly quota)",
    description=(
        "Remove the freeze row for ``problem_id`` so the card re-enters "
        "the daily-plan queue immediately. **The weekly quota is not "
        "refunded** — critic C8 on ``adhd_ux_full_phase14.md``. Returns "
        "204 on success, 404 when no active freeze exists."
    ),
)
async def delete_freeze(
    problem_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete the freeze row; 404 if nothing to delete."""

    deleted = await unfreeze_card(db, user.id, problem_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "no_active_freeze", "problem_id": str(problem_id)},
        )
    return None


__all__ = ["router"]
