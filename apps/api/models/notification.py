"""Persistent notification model — replaces in-memory notification store."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Boolean, func, Index
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, is_sqlite


class Notification(Base):
    """Push notification persisted in the database."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50))
    # Categories: reminder, weekly_prep, fsrs_review, progress, inactivity, goal
    read: Mapped[bool] = mapped_column(Boolean, default=False)

    # Batching & deduplication
    batch_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    dedup_key: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    # Priority: "low", "normal", "high", "urgent"
    priority: Mapped[str] = mapped_column(String(20), default="normal")

    # Scheduled delivery (None = immediate)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Channels actually used for delivery: ["sse", "web_push"]
    sent_via: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True)

    # Actionable notification: deep-link URL + button label
    action_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    action_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Extensible metadata for frontend routing context
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Conditional partial index (PostgreSQL only; SQLite does not support partial unique indexes)
if not is_sqlite():
    Index(
        "ix_notification_dedup_key",
        Notification.dedup_key,
        unique=True,
        postgresql_where=Notification.dedup_key.isnot(None),
    )
