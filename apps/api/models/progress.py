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
from models.compat import CompatUUID, CompatJSONB
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
    ease_factor: Mapped[float] = mapped_column(Float, default=2.5)  # legacy SM-2 compat
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


class LearningTemplate(Base):
    """Reusable learning templates (5 built-in + user-created).

    Templates define default preferences for specific learning styles.
    Reference: spec Phase 1 — learning template system.
    """

    __tablename__ = "learning_templates"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    # Template preferences (key-value pairs)
    preferences: Mapped[dict] = mapped_column(CompatJSONB, default=dict)
    # e.g. {"note_format": "step_by_step", "detail_level": "detailed", ...}

    # v3: Scene binding
    scene_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Scene this template maps to (e.g. "exam_prep", "study_session")
    tab_preset: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    # Tab layout for this template [{"type": "notes", "position": 0}, ...]
    workflow: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # AI workflow identifier

    # Template metadata
    target_audience: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    # e.g. "STEM student", "Language learner", "Visual learner"
    tags: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
