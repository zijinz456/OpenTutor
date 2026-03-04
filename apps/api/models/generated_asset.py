"""Versioned generated assets for notes, study plans, and flashcards."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from models.compat import CompatJSONB, CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class GeneratedAsset(Base):
    """Stores versioned AI-generated assets outside the core question bank."""

    __tablename__ = "generated_assets"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"), nullable=False)
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("courses.id"), nullable=True)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[dict] = mapped_column(CompatJSONB, nullable=False)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", CompatJSONB, nullable=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, nullable=False, default=uuid.uuid4)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
