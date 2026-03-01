"""Channel binding model — maps external messaging identifiers to User records.

Supports multi-channel access (WhatsApp, iMessage, etc.) by binding external
channel identifiers (phone numbers, handles) to internal User accounts.
Each binding tracks its own active course context for stateless messaging.
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, func, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ChannelBinding(Base):
    """Binds an external messaging identity to an internal User."""

    __tablename__ = "channel_bindings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    # External channel identity
    channel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # e.g. "whatsapp", "imessage", "telegram"
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # e.g. phone number "+1234567890", iMessage handle "user@icloud.com"

    display_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # Per-channel active course context (stateless messaging needs this)
    active_course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )

    # Extensible metadata (e.g. push token, locale, profile picture URL)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("channel_type", "channel_id", name="uq_channel_type_id"),
        Index("ix_channel_binding_user_id", "user_id"),
        Index("ix_channel_binding_type_id", "channel_type", "channel_id"),
    )
