"""Per-user notification preferences — channels, quiet hours, frequency caps."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class NotificationSettings(Base):
    """Per-user notification delivery preferences."""

    __tablename__ = "notification_settings"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )

    # Enabled notification channels: ["sse", "web_push", "whatsapp", "imessage"]
    channels_enabled: Mapped[list] = mapped_column(CompatJSONB, default=lambda: ["sse"])

    # Quiet hours — notifications are held during this window
    quiet_hours_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "22:00"
    quiet_hours_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "08:00"
    timezone: Mapped[str] = mapped_column(String(50), default="UTC")

    # Frequency caps
    max_notifications_per_hour: Mapped[int] = mapped_column(Integer, default=5)
    max_notifications_per_day: Mapped[int] = mapped_column(Integer, default=20)

    # Learned study timing (updated by timing analysis)
    preferred_study_time: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)  # "14:30"
    study_time_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Escalation: if notification not read, re-send via another channel
    escalation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    escalation_delay_hours: Mapped[int] = mapped_column(Integer, default=4)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
