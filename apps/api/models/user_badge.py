"""User-badge ORM — Phase 16c Bundle C (Badge backend, Subagent A scope).

One row per ``(user_id, badge_key)`` pair the user has unlocked.
``user.unlocked_badges`` is **derived** at query time from this table —
no materialized "unlock count" column on ``users`` avoids drift between
the cached number and the source-of-truth ledger.

Key shape:

* ``badge_key`` — short string tag matching one of the
  :data:`services.gamification.badge_service.CATALOG` entries (e.g.
  ``"first_card"``, ``"7_day_streak"``). Plain ``String(64)`` so adding
  a new badge never needs a migration.
* ``unlocked_at`` — timestamp of the first qualifying event. Once set
  the row is never updated; subsequent qualifying events are absorbed
  by the unique constraint.
* ``metadata_json`` — optional context blob captured at unlock time
  (e.g. the XP total that triggered the threshold crossing). Most
  unlocks store ``None``; the column exists so future predicates can
  carry trigger context without a schema change.

The ``UniqueConstraint(user_id, badge_key)`` is the durable
once-per-(user, badge) guard called for in Bundle C spec D.1. Service
code wraps inserts in a savepoint and treats UNIQUE violations as
"already unlocked" (idempotent award).

Style mirrors :mod:`models.xp_event` and :mod:`models.freeze_token` —
``Mapped`` / ``mapped_column``, ``CompatUUID`` for SQLite/Postgres
parity, tz-aware ``DateTime(timezone=True)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.compat import CompatJSONB, CompatUUID


class UserBadge(Base):
    """One badge unlock for one user. Append-only, never updated."""

    __tablename__ = "user_badges"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    badge_key: Mapped[str] = mapped_column(String(64), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    __table_args__ = (
        # Durable one-time unlock — a second award attempt for the same
        # ``(user, badge)`` is rejected at the DB layer and swallowed by
        # the service. Bundle C spec D.1.
        UniqueConstraint("user_id", "badge_key", name="uq_user_badges_user_badge"),
        # Hot dashboard / profile path: "all unlocks for this user".
        # The FK column already has ``index=True`` above; this composite
        # index is for the future case where we filter by badge as well.
        Index("ix_user_badges_user_badge", "user_id", "badge_key"),
    )


__all__ = ["UserBadge"]
