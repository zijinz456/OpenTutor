"""Persistent chat message log for session history restore."""

import uuid
from datetime import datetime

from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from models.compat import CompatJSONB, CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ChatMessageLog(Base):
    """Stores user and assistant turns for each chat session."""

    __tablename__ = "chat_message_logs"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_chat_message_session_created", "session_id", "created_at"),
    )
