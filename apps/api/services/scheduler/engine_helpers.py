"""Scheduler engine helpers — shared utilities for scheduler jobs.

Provides user iteration, notification, and backward-compatible SSE stubs.
"""

import logging
import uuid

from sqlalchemy import select

from sqlalchemy.exc import SQLAlchemyError

from database import async_session
from models.user import User

logger = logging.getLogger(__name__)


# No-op stubs for removed SSE subscriber management (backward compatibility).
async def subscribe_sse(*a, **kw):
    pass


async def unsubscribe_sse(*a, **kw):
    pass


async def _get_user_ids() -> list[uuid.UUID]:
    """Fetch all user IDs in a short-lived session.

    Used by scheduler jobs so each user can be processed in its own
    isolated session — preventing one user's DB error from corrupting
    the session state for subsequent users.
    """
    async with async_session() as db:
        result = await db.execute(select(User.id))
        return [row[0] for row in result.all()]


async def _for_each_user(processor, label: str) -> int:
    """Run a processor callback for every user, each in its own DB session.

    ``processor(user_id, db)`` should return a truthy value when the
    operation counted as successful.  Exceptions are logged and
    do not abort the loop.

    Returns the count of successful invocations.
    """
    user_ids = await _get_user_ids()
    count = 0
    for user_id in user_ids:
        try:
            async with async_session() as db:
                result = await processor(user_id, db)
                if result:
                    count += 1
        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
            logger.exception("%s failed for user %s", label, user_id)
    return count


async def _push_notification(
    user_id: uuid.UUID,
    title: str,
    body: str,
    category: str = "reminder",
    **kwargs,
):
    """Store an in-app notification for the user."""
    try:
        from models.notification import Notification

        async with async_session() as db:
            notif = Notification(
                user_id=user_id,
                title=title,
                body=body,
                category=category,
                metadata_json=kwargs.get("data"),
            )
            db.add(notif)
            await db.commit()
            logger.debug("Notification stored: [%s] %s for user %s", category, title, user_id)
    except (SQLAlchemyError, ImportError) as e:
        logger.exception("Failed to store notification for user %s", user_id)
