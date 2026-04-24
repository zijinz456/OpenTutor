"""Learning path + path-room ORM — Phase 16a T1 Python Paths UI.

Two tables materialize the TryHackMe-style room view over the 581 cards
already seeded from ``content/python_full_curriculum.yaml``.

- ``learning_paths`` — one row per track (e.g. Python Fundamentals). The
  ``track_id`` column holds the yaml ``track_id`` so the seed script can
  idempotently match yaml → row without a second lookup table.
- ``path_rooms`` — ordered rooms within a path. ``room_order`` is a
  0-based dense index inside the path; the unique constraint on
  ``(path_id, room_order)`` guards against accidental duplicates from a
  re-seed.

No ``user_path_progress`` table (critic C5) — per-user progress is
**derived** from ``PracticeResult`` rows. Adding a progress table would
introduce a second source of truth that drifts on FSRS resets. The
trade-off (one extra indexed query per path page load) is paid happily.

Task-to-room mapping is a column on ``practice_problems``
(``path_room_id`` + ``task_order``) rather than a join table — a problem
belongs to at most one room within a path, so a join table would
duplicate the FK.

Style mirrors Phase 5 ``interview.py`` and Phase 14 ``freeze_token.py``
(``Mapped`` / ``mapped_column``, ``CompatUUID``, tz-aware
``DateTime(timezone=True)``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.compat import CompatUUID


class LearningPath(Base):
    """One track-level learning path (e.g. Python Fundamentals).

    ``slug`` is globally unique (not per-course) because paths are
    identified in URLs as ``/path/{slug}`` without a course prefix.
    ``track_id`` is the yaml track identifier and is indexed separately
    so the seed script's idempotent lookup is cheap.
    """

    __tablename__ = "learning_paths"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # ``beginner`` | ``intermediate`` | ``advanced`` — plain string so
    # adding a new tier never needs a migration.
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    # yaml ``track_id`` e.g. ``python_fundamentals``.
    track_id: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Consumed by the seed script for a per-path progress caption
    # ("12 / 40 rooms") when the import is incremental.
    room_count_target: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    rooms = relationship(
        "PathRoom",
        back_populates="path",
        cascade="all, delete-orphan",
        order_by="PathRoom.room_order",
    )

    __table_args__ = (
        Index("ix_learning_paths_slug", "slug"),
        Index("ix_learning_paths_track_id", "track_id"),
    )


class PathRoom(Base):
    """Ordered room inside a ``LearningPath``.

    Room slug is unique per path (not global) — two different paths can
    each have a ``py_intro`` room. Room order is also unique per path so
    a dev never accidentally double-orders two rooms to the same slot.
    """

    __tablename__ = "path_rooms"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    path_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("learning_paths.id", ondelete="CASCADE"),
        nullable=False,
    )
    # yaml module slug e.g. ``py_intro``; 80 chars to leave headroom for
    # future tracks whose module ids may be longer than the 60-char path
    # slug cap.
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 0-based dense index within the parent path.
    room_order: Mapped[int] = mapped_column(Integer, nullable=False)
    # First scraped chunk rendered as markdown above the task list. Can
    # be long — ``Text`` not ``String`` — and is trimmed to ~4k chars by
    # the service layer (critic C7).
    intro_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # One-line practical outcome surfaced on the mission card/hero.
    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 1..5 difficulty scale for later hero + filtering work.
    difficulty: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Estimated time in minutes. Nullable at schema level so legacy rows
    # can migrate in one pass; the seed/migration backfill supplies 15.
    eta_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Optional grouping label like "Basics" or "Advanced".
    module_label: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    # Target card count from the yaml module (for the "3/15 tasks" UI
    # label when a room has no mapped tasks yet).
    task_count_target: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    path = relationship("LearningPath", back_populates="rooms")
    # ``foreign_keys`` pin is required because ``PracticeProblem`` already
    # has a self-referencing FK (``parent_problem_id``) — without the pin
    # SQLAlchemy can't pick which FK this relationship rides.
    tasks = relationship(
        "PracticeProblem",
        foreign_keys="PracticeProblem.path_room_id",
        order_by="PracticeProblem.task_order",
    )

    __table_args__ = (
        UniqueConstraint("path_id", "slug", name="uq_path_room_slug_per_path"),
        UniqueConstraint("path_id", "room_order", name="uq_path_room_order_per_path"),
        Index("ix_path_rooms_path", "path_id"),
    )
