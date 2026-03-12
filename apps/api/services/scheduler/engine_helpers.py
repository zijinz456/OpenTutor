"""Scheduler engine helpers — shared utilities for scheduler jobs.

Provides user iteration, notification, and backward-compatible SSE stubs.
"""

import inspect
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
    *,
    course_id: uuid.UUID | None = None,
    dedup_key: str | None = None,
    batch_key: str | None = None,
    priority: str | None = None,
    action_url: str | None = None,
    action_label: str | None = None,
    data: dict | None = None,
    scheduled_for=None,
    **kwargs,
) -> bool:
    """Store an in-app notification for the user.

    Returns:
        True if inserted, False if skipped (dedup) or failed.
    """
    try:
        from models.notification import Notification

        async with async_session() as db:
            if dedup_key:
                existing = await db.execute(
                    select(Notification.id).where(
                        Notification.user_id == user_id,
                        Notification.dedup_key == dedup_key,
                    ).limit(1)
                )
                if existing.scalar_one_or_none() is not None:
                    logger.debug(
                        "Notification dedup skip: [%s] %s for user %s (%s)",
                        category,
                        title,
                        user_id,
                        dedup_key,
                    )
                    return False

            notif = Notification(
                user_id=user_id,
                course_id=course_id,
                title=title,
                body=body,
                category=category,
                batch_key=batch_key,
                dedup_key=dedup_key,
                priority=priority,
                action_url=action_url,
                action_label=action_label,
                metadata_json=data if data is not None else kwargs.get("data"),
                scheduled_for=scheduled_for,
            )
            add_result = db.add(notif)
            # Test doubles sometimes model `add` as async; production AsyncSession.add is sync.
            if inspect.isawaitable(add_result):
                await add_result
            await db.commit()
            logger.debug("Notification stored: [%s] %s for user %s", category, title, user_id)
            return True
    except (SQLAlchemyError, ValueError, TypeError, RuntimeError, OSError):
        logger.exception("Failed to store notification for user %s", user_id)
        return False
