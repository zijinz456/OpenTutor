"""Study goal model — durable user goals linked to agent work."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from models.compat import CompatJSONB, CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class StudyGoal(Base):
    """High-level learning goal owned by a user and optionally scoped to a course."""

    __tablename__ = "study_goals"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID,
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    success_metric: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    current_milestone: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    next_action: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    confidence: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    target_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_study_goal_user_course_status_created", "user_id", "course_id", "status", "created_at"),
        Index("ix_study_goal_user_status_target", "user_id", "status", "target_date"),
    )
