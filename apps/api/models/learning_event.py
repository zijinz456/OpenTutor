"""xAPI-inspired standardized learning events.

Every learning activity (quiz attempt, flashcard review, note creation,
exercise completion, mastery update) emits a ``LearningEvent`` for unified
analytics, BKT/FSRS updates, and plugin hooks.

Verb vocabulary (subset of xAPI):
- attempted: Started an activity (quiz, exercise)
- answered: Submitted an answer
- completed: Finished an activity
- reviewed: Reviewed a flashcard
- mastered: Achieved mastery threshold on a topic
- created: Created a learning artifact (note, flashcard)
- failed: Failed an assessment
- progressed: Made progress on a topic/course

Inspired by:
- H5P xAPI event model (attempted, answered, completed)
- Open edX CompletableXBlockMixin + ScorableXBlockMixin
- ADL xAPI specification (actor, verb, object, result, context)
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class LearningEvent(Base):
    """Standardized learning event record."""

    __tablename__ = "learning_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Actor — who performed the action
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Verb — what action was performed
    verb: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # attempted | answered | completed | reviewed | mastered | created | failed | progressed

    # Object — what was acted upon
    object_type: Mapped[str] = mapped_column(
        String(32), nullable=False
    )  # quiz | flashcard | note | exercise | topic | course
    object_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # UUID or identifier of the specific item

    # Result — outcome of the action
    score: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # 0.0 - 1.0 normalized score
    success: Mapped[Optional[bool]] = mapped_column(
        nullable=True
    )  # True = correct/passed, False = incorrect/failed
    completion: Mapped[Optional[bool]] = mapped_column(
        nullable=True
    )  # True = fully completed
    duration_seconds: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # Time spent on this activity
    result_json: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # Additional result data (e.g., individual answers)

    # Context — surrounding information
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=True,
    )
    agent_name: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # Which agent triggered this event
    session_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # Chat session context
    context_json: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True
    )  # Additional context (scene, topic, parent_event_id)

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_learning_event_user_ts", "user_id", "timestamp"),
        Index("ix_learning_event_verb", "verb"),
        Index("ix_learning_event_object", "object_type", "object_id"),
        Index("ix_learning_event_course", "course_id", "timestamp"),
    )
