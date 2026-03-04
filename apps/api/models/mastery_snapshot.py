"""Append-only mastery time-series table (Phase 4).

Records a snapshot of mastery_score each time a quiz result updates progress.
Enables analytics time-series charts showing mastery growth over time.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index
from models.compat import CompatUUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base


class MasterySnapshot(Base):
    __tablename__ = "mastery_snapshots"
    __table_args__ = (
        Index("ix_mastery_snap_user_course_time", "user_id", "course_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False,
    )
    content_node_id: Mapped[uuid.UUID | None] = mapped_column(
        CompatUUID, nullable=True,
    )
    mastery_score: Mapped[float] = mapped_column(sa.Float, nullable=False)
    gap_type: Mapped[str | None] = mapped_column(sa.String(30), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
