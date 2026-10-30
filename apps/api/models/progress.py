"""Learning progress tracking model.

Tracks progress at three granularity levels:
- Course level
- Chapter level
- Knowledge point level

Reference: spec Phase 1 — course → chapter → knowledge point granularity.
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Float, Integer, func
from models.compat import CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class LearningProgress(Base):
    """Tracks learning progress per content node."""

    __tablename__ = "learning_progress"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"))
    content_node_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("course_content_tree.id", ondelete="CASCADE"), nullable=True
    )

    # Progress tracking
    status: Mapped[str] = mapped_column(String(20), default="not_started")
    # Status: not_started, in_progress, reviewed, mastered
    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    # 0.0 = not started, 1.0 = fully mastered

    # Study metrics
    time_spent_minutes: Mapped[int] = mapped_column(Integer, default=0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    quiz_attempts: Mapped[int] = mapped_column(Integer, default=0)
    quiz_correct: Mapped[int] = mapped_column(Integer, default=0)

    # v4: Layer progression diagnosis
    gap_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # fundamental_gap | transfer_gap | trap_vulnerability | mastered

    # Spaced repetition — FSRS-4.5 fields
    next_review_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)
    fsrs_difficulty: Mapped[float] = mapped_column(Float, default=5.0)  # 1-10
    fsrs_stability: Mapped[float] = mapped_column(Float, default=0.0)  # days until 90% recall
    fsrs_reps: Mapped[int] = mapped_column(Integer, default=0)
    fsrs_lapses: Mapped[int] = mapped_column(Integer, default=0)
    fsrs_state: Mapped[str] = mapped_column(String(20), default="new")  # new|learning|review|relearning

    last_studied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
