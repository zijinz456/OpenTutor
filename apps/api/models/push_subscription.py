"""Web Push subscription model — stores VAPID push endpoints per user."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Text, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PushSubscription(Base):
    """Browser Web Push subscription for a user."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )

    # Push service URL (unique per browser/device)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)

    # VAPID key pair from the browser
    p256dh_key: Mapped[str] = mapped_column(String(200), nullable=False)
    auth_key: Mapped[str] = mapped_column(String(200), nullable=False)

    # Optional browser identification
    user_agent: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_push_sub_user_id", "user_id"),
        Index("ix_push_sub_endpoint", "endpoint", unique=True),
    )
