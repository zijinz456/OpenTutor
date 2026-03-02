"""Scene system models — scene definitions for AI behavior tuning.

Scene is an internal backend concept used by the policy engine to adjust AI behavior
based on detected study context (exam prep, review drill, etc.).
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Boolean, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Scene(Base):
    """Scene definition — preset or user-created.

    Scenes drive: AI workflow, system prompt behavior, and preference overrides.
    Scene detection is automatic via the policy engine — no manual switching UI.
    """

    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    is_preset: Mapped[bool] = mapped_column(Boolean, default=False)

    # Tab layout configuration for this scene
    tab_preset: Mapped[list[dict]] = mapped_column(JSONB, nullable=False)

    # AI workflow identifier
    workflow: Mapped[str] = mapped_column(String(50), nullable=False)

    # AI behavior rules injected into system prompt
    ai_behavior: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Default preference overrides for this scene
    preferences: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
