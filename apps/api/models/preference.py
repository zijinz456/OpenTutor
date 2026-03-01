"""Preference models — 7-layer cascade (temporary → course_scene → course → global_scene → global → template → default)."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import Index, String, DateTime, ForeignKey, Text, Float, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class UserPreference(Base):
    """Confirmed user preferences with 7-layer cascade.

    Priority (highest first): temporary → course_scene → course → global_scene → global → template → system_default.
    """

    __tablename__ = "user_preferences"
    __table_args__ = (
        Index("ix_user_preference_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )

    # Preference scope: temporary | course_scene | course | global_scene | global | template
    scope: Mapped[str] = mapped_column(String(20), default="global")

    # Scene type for scene-scoped preferences (e.g. "exam_prep", "study_session")
    scene_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Preference data
    dimension: Mapped[str] = mapped_column(String(50))  # e.g. "note_format", "detail_level", "language"
    value: Mapped[str] = mapped_column(Text)  # e.g. "bullet_point", "concise", "zh-CN"
    source: Mapped[str] = mapped_column(String(20), default="onboarding")  # onboarding | nl_command | behavior

    # Confidence
    confidence: Mapped[float] = mapped_column(Float, default=0.5)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user = relationship("User", back_populates="preferences")


class PreferenceSignal(Base):
    """Raw preference signals extracted from user behavior.

    Collected by the Compiler (openakita pattern) and processed into
    UserPreference entries after confidence threshold is reached.
    """

    __tablename__ = "preference_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )

    # Signal data
    signal_type: Mapped[str] = mapped_column(String(20))  # explicit | modification | behavior | negative
    dimension: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(Text)
    context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # Source conversation/action context

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
