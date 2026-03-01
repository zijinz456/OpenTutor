"""Batch collector — merges rapid-fire notifications into a single digest.

When multiple notifications share the same batch_key within a 60-second
window, they are merged into one notification instead of being sent
individually. This prevents notification fatigue from burst events
(e.g., multiple FSRS cards becoming due simultaneously).
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from services.notification.dispatcher import dispatch

logger = logging.getLogger(__name__)

# Window in seconds for merging notifications with the same batch_key
BATCH_WINDOW_SECONDS = 60


async def collect_or_send(
    user_id: uuid.UUID,
    batch_key: str,
    title: str,
    body: str,
    items: list[str],
    *,
    category: str = "reminder",
    course_id: uuid.UUID | None = None,
    priority: str = "normal",
    db: AsyncSession,
) -> Notification | None:
    """Collect items into a batched notification, or send if batch window has passed.

    Args:
        user_id: Target user.
        batch_key: Key for grouping related notifications.
        title: Notification title (used for new notifications).
        body: Base body text.
        items: List of items to include in the notification body.
        category: Notification category.
        course_id: Optional associated course.
        priority: Notification priority level.
        db: Database session.

    Returns:
        Notification if dispatched, None if merged into existing batch.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=BATCH_WINDOW_SECONDS)

    # Check for an existing notification with same batch_key within the window
    result = await db.execute(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.batch_key == batch_key,
            Notification.created_at >= cutoff,
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        # Merge into existing notification body
        merged_items = existing.body
        for item in items:
            if item not in merged_items:
                merged_items += f"\n- {item}"

        existing.body = merged_items
        await db.commit()

        logger.debug(
            "Batch merged into existing notification %s (batch_key=%s)",
            existing.id, batch_key,
        )
        return None

    # No recent batch — create and dispatch a new notification
    if items:
        full_body = body + "\n" + "\n".join(f"- {item}" for item in items)
    else:
        full_body = body

    notification = await dispatch(
        user_id=user_id,
        title=title,
        body=full_body,
        category=category,
        course_id=course_id,
        priority=priority,
        batch_key=batch_key,
        db=db,
    )

    return notification
