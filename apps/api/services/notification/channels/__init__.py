"""Notification channel abstraction — pluggable delivery backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification


@dataclass
class DeliveryResult:
    """Result of a single channel delivery attempt."""

    status: str  # "sent", "failed", "skipped"
    error: str | None = None


class NotificationChannel(ABC):
    """Abstract base for notification delivery channels."""

    name: str = "base"

    @abstractmethod
    async def send(
        self,
        user_id: uuid.UUID,
        notification: Notification,
        db: AsyncSession,
    ) -> DeliveryResult:
        """Deliver a notification to a user through this channel."""
        ...

    @abstractmethod
    async def is_available(self, user_id: uuid.UUID, db: AsyncSession) -> bool:
        """Check whether this channel can reach the given user."""
        ...
