"""Freeze-token persistence — Phase 14 T1 ADHD UX "❄ Freeze" quota.

One row per freeze event. A freeze hides a practice problem from the
daily-plan selector for 24 hours without touching ``learning_progress``
(no FSRS write, no shame loop). The weekly quota of three freezes per
user is enforced by the service layer on top of a timestamp filter over
this table — a separate counter column would duplicate state and could
drift on clock-skew; counting rows is the single source of truth.

The ``(user_id, problem_id)`` uniqueness constraint is a **lifetime**
cap per card: if you froze ``pydantic-v2-migrations`` once, you can't
freeze it again ever. Gives us a cheap guardrail against "freeze every
hard card" avoidance (critic C1 on ``plan/adhd_ux_full_phase14.md``)
without a second state machine. Phase 15 can revisit if the cap proves
too tight in practice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.compat import CompatUUID


class FreezeToken(Base):
    """A single 24-hour freeze of one practice problem for one user.

    Fields mirror the Phase 5 ``InterviewSession`` ORM style — ``CompatUUID``
    for cross-dialect UUID storage and ``DateTime(timezone=True)`` for
    timestamps so Postgres keeps tz info and SQLite round-trips ISO
    strings. ``frozen_at`` defaults to ``datetime.now(timezone.utc)`` on
    the Python side rather than ``server_default=func.now()`` because
    ``expires_at = frozen_at + 24h`` is computed in the service and must
    be deterministic across both clocks; relying on two different server
    clocks (one for each column) would introduce sub-second drift.
    """

    __tablename__ = "freeze_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    problem_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("practice_problems.id", ondelete="CASCADE"),
        nullable=False,
    )
    frozen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        # Composite index on (user_id, expires_at) makes the two hot
        # queries — "active freezes for user" and "weekly quota count
        # for user" — index-only scans on Postgres. No index on
        # ``problem_id`` alone: the uniqueness constraint already covers
        # the per-problem lookup pattern used by the 409-guard.
        Index("ix_freeze_tokens_user_expires", "user_id", "expires_at"),
        UniqueConstraint("user_id", "problem_id", name="uq_freeze_token_user_problem"),
    )


__all__ = ["FreezeToken"]
