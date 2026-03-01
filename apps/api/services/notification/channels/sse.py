"""SSE notification channel — pushes to in-process subscriber queues.

Wraps the existing SSE subscriber pattern from services.scheduler.engine,
providing it through the unified NotificationChannel interface.
"""

import asyncio
import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from services.notification.channels import NotificationChannel, DeliveryResult

logger = logging.getLogger(__name__)

# SSE subscribers: str(user_id) → list[asyncio.Queue]
_sse_subscribers: dict[str, list[asyncio.Queue]] = {}


def subscribe_sse(user_id: uuid.UUID) -> asyncio.Queue:
    """Create an SSE subscription queue for a user."""
    queue: asyncio.Queue = asyncio.Queue()
    key = str(user_id)
    _sse_subscribers.setdefault(key, []).append(queue)
    logger.debug("SSE subscriber added for user %s (total: %d)", key, len(_sse_subscribers[key]))
    return queue


def unsubscribe_sse(user_id: uuid.UUID, queue: asyncio.Queue) -> None:
    """Remove an SSE subscription."""
    key = str(user_id)
    subs = _sse_subscribers.get(key, [])
    if queue in subs:
        subs.remove(queue)
        logger.debug("SSE subscriber removed for user %s (remaining: %d)", key, len(subs))


class SSEChannel(NotificationChannel):
    """Delivers notifications via Server-Sent Events to connected browsers."""

    name = "sse"

    async def send(
        self,
        user_id: uuid.UUID,
        notification: Notification,
        db: AsyncSession,
    ) -> DeliveryResult:
        """Push notification payload to all SSE subscriber queues for this user."""
        payload = json.dumps({
            "id": str(notification.id),
            "title": notification.title,
            "body": notification.body,
            "category": notification.category,
            "priority": notification.priority,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        })

        key = str(user_id)
        queues = _sse_subscribers.get(key, [])
        pushed = 0

        for queue in queues:
            try:
                queue.put_nowait(payload)
                pushed += 1
            except asyncio.QueueFull:
                logger.warning("SSE queue full for user %s, dropping notification", key)
            except Exception as e:
                logger.warning("SSE push error for user %s: %s", key, e)

        logger.debug("SSE: pushed to %d/%d queues for user %s", pushed, len(queues), key)
        if pushed > 0:
            return DeliveryResult(status="sent")
        return DeliveryResult(status="skipped", error="No active SSE subscribers")

    async def is_available(self, user_id: uuid.UUID, db: AsyncSession) -> bool:
        """SSE is always available — subscribers may connect later."""
        return True
