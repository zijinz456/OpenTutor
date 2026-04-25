"""XP event ORM — Phase 16c gamification, Subagent A scope.

Append-only ledger of every XP grant or deduction the system records.
``user.xp_total`` is **derived** from ``SUM(xp_events.amount) WHERE user_id=?``
on read (Story 1 #6) — no materialized total column avoids drift between
the cached number and the source-of-truth ledger.

Key shape:

* ``source`` — short string tag (e.g. ``"practice_result"``,
  ``"room_complete"``, ``"manual"``). Plain ``String(64)`` so adding a
  new source never needs a migration.
* ``source_id`` — nullable FK-shaped reference to whatever produced the
  event (problem id, room id, ...). Nullable because manual grants and
  freeze-saver bookkeeping rows have no external source row.
* ``metadata_json`` — renamed from ``metadata`` to avoid the SQLAlchemy
  ``Base.metadata`` attribute collision (``Mapped`` declarative models
  cannot use ``metadata`` as a column attr).
* Anti-spam: a UNIQUE index on ``(user_id, source_id, date(earned_at))``
  prevents the same source_id awarding twice in one UTC day. Enforced by
  the migration; the ORM only declares the column shapes.

CHECK constraint ``amount BETWEEN -5 AND 200`` is in the migration as a
table constraint and surfaced here too via ``__table_args__`` so
``Base.metadata.create_all`` (used by the test harness) emits the same
guard.

Style mirrors ``models/freeze_token.py`` and ``models/learning_path.py``
— ``Mapped`` / ``mapped_column``, ``CompatUUID`` for SQLite/Postgres
parity, tz-aware ``DateTime(timezone=True)``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from models.compat import CompatJSONB, CompatUUID


class XpEvent(Base):
    """One row per XP grant/deduction. Append-only, never updated."""

    __tablename__ = "xp_events"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    # CHECK constraint enforces the bounds at the DB level. Pure-fn
    # ``compute_xp`` clamps before insert, but the constraint is the
    # final guard against a service bug grafting bad numbers in.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, nullable=True)
    # Renamed from ``metadata`` — SQLAlchemy reserves that name on the
    # declarative ``Base`` for table metadata access.
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    earned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint(
            "amount BETWEEN -5 AND 200",
            name="ck_xp_events_amount_range",
        ),
        # Hot dashboard path: "events for this user, newest first".
        Index("ix_xp_events_user_earned", "user_id", "earned_at"),
        # Anti-spam: per Story 2 #3, max one event per
        # ``(user_id, source_id, UTC-day)``. Functional partial unique
        # index — works on SQLite (3.8+) and Postgres. The model
        # declares it so ``Base.metadata.create_all`` (used by the test
        # harness) emits the same dedup guard the migration produces.
        Index(
            "uq_xp_events_user_source_day",
            "user_id",
            "source_id",
            text("date(earned_at)"),
            unique=True,
            sqlite_where=text("source_id IS NOT NULL"),
            postgresql_where=text("source_id IS NOT NULL"),
        ),
    )
