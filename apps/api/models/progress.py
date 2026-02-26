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

from sqlalchemy import String, DateTime, ForeignKey, Text, Float, Integer, Boolean, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class LearningProgress(Base):
    """Tracks learning progress per content node."""

    __tablename__ = "learning_progress"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"))
    content_node_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_content_tree.id"), nullable=True
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

    # Spaced repetition (Phase 2: FSRS)
    next_review_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)
    interval_days: Mapped[int] = mapped_column(Integer, default=0)

    last_studied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LearningTemplate(Base):
    """Reusable learning templates (5 built-in + user-created).

    Templates define default preferences for specific learning styles.
    Reference: spec Phase 1 — learning template system.
    """

    __tablename__ = "learning_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Template preferences (key-value pairs)
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict)
    # e.g. {"note_format": "step_by_step", "detail_level": "detailed", ...}

    # Template metadata
    target_audience: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # e.g. "STEM student", "Language learner", "Visual learner"
    tags: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
