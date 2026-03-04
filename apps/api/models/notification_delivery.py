"""Notification delivery tracking — per-channel delivery status and escalation."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, func, UniqueConstraint
from models.compat import CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class NotificationDelivery(Base):
    """Tracks delivery of a notification through a specific channel."""

    __tablename__ = "notification_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("notifications.id", ondelete="CASCADE")
    )

    # Channel used: "sse", "web_push", "whatsapp", "imessage"
    channel: Mapped[str] = mapped_column(String(30), nullable=False)

    # Delivery lifecycle: pending → sent → delivered → read | failed | skipped
    status: Mapped[str] = mapped_column(String(20), default="pending")

    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Escalation tracking
    is_escalation: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_from_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID,
        ForeignKey("notification_deliveries.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("notification_id", "channel", name="uq_notification_channel"),
    )
