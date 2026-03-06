"""In-app notifications — lightweight model for Heartbeat and proactive alerts."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, DateTime, Boolean, ForeignKey, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Notification(Base):
    """A user-facing notification (review reminders, weekly reports, etc.)."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)

    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), default="reminder")

    read: Mapped[bool] = mapped_column(Boolean, default=False)

    # Deduplication and batching
    batch_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    dedup_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Scheduling and delivery
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_via: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    # Action link
    action_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    action_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Structured data (concepts at risk, urgent count, etc.)
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
