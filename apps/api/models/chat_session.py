"""Chat session model — per-course per-scene conversation tracking."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, func, Index
from models.compat import CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ChatSession(Base):
    """Tracks conversation sessions, each bound to a course + scene."""

    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"))

    scene_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(30), default="web", nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_chat_session_user_course", "user_id", "course_id"),
        Index("ix_chat_session_user_course_updated", "user_id", "course_id", "updated_at"),
    )
