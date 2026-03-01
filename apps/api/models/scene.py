"""Scene system models — v3 scene switching system.

Supports preset + custom scenes with UI state snapshots and switch logging.
Each course has an active_scene that drives preference cascade, AI behavior, and Tab layout.
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Boolean, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Scene(Base):
    """Scene definition — preset or user-created.

    Scenes drive: Tab layout, AI workflow, system prompt behavior, and preference overrides.
    """

    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)

    # Tab layout configuration for this scene
    tab_preset: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    # e.g. [{"type": "notes", "position": 0}, {"type": "quiz", "position": 1}]

    # AI workflow identifier
    workflow: Mapped[str] = mapped_column(String(50), nullable=False)

    # AI behavior rules injected into system prompt
    ai_behavior: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # e.g. {"style": "concise", "focus": "weak_points", "quiz_priority": "high_freq"}

    # Default preference overrides for this scene
    preferences: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # e.g. {"note_format": "bullet_summary", "detail_level": "concise"}

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SceneSnapshot(Base):
    """Per-course per-scene UI state snapshot.

    Saved when switching away from a scene, restored when switching back.
    """

    __tablename__ = "scene_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"))
    scene_id: Mapped[str] = mapped_column(String(50), nullable=False)

    # UI state
    open_tabs: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)
    # [{"type": "notes", "config": {...}, "position": 0}]
    layout_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # {"panel_sizes": [25, 25, 25, 25], "hidden_panels": []}
    scroll_positions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    last_active_tab: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("course_id", "scene_id", name="uq_snapshot_course_scene"),
    )


class SceneSwitchLog(Base):
    """Scene switch history for analytics and AI suggestion tuning."""

    __tablename__ = "scene_switch_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    from_scene: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    to_scene: Mapped[str] = mapped_column(String(50), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # "manual" | "ai_suggested" | "auto"
    trigger_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
