"""Notification bridge — push scheduler notifications to messaging channels.

Bridges the internal notification system (scheduler reminders, progress alerts,
FSRS review prompts) to external messaging channels. When a notification is
generated for a user who has channel bindings, this module delivers it via
their connected messaging platforms.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.channel_binding import ChannelBinding
from services.channels.base import OutgoingMessage
from services.channels.formatter import format_for_channel

logger = logging.getLogger(__name__)

# Notification category icons for channel messages
_CATEGORY_ICONS = {
    "reminder": "Reminder",
    "weekly_prep": "Weekly Prep",
    "fsrs_review": "Review Due",
    "progress": "Progress Update",
    "inactivity": "We Miss You",
    "goal": "Goal Update",
}


async def push_notification_to_channels(
    user_id,
    title: str,
    body: str,
    category: str,
    db_factory,
) -> None:
    """Send a notification to all of a user's connected messaging channels.

    Called by the scheduler/activity engine when generating notifications.
    Failures on individual channels are logged and skipped — one channel's
    error should not block delivery to other channels.

    Args:
        user_id: The user's UUID.
        title: Notification title (e.g. "Time to review!").
        body: Notification body text.
        category: Notification category (e.g. "fsrs_review", "reminder").
        db_factory: Async session factory for database access.
    """
    try:
        async with db_factory() as db:
            # 1. Query all ChannelBindings for this user
            stmt = select(ChannelBinding).where(ChannelBinding.user_id == user_id)
            result = await db.execute(stmt)
            bindings = result.scalars().all()

            if not bindings:
                logger.debug("No channel bindings for user %s — skipping push", user_id)
                return

            # 2. Format notification text
            category_label = _CATEGORY_ICONS.get(category, category.replace("_", " ").title())
            notification_text = _format_notification(category_label, title, body)

            # 3. Send to each bound channel
            from services.channels.registry import get_adapter

            delivered = 0
            for binding in bindings:
                try:
                    adapter = get_adapter(binding.channel_type)
                    formatted = format_for_channel(notification_text, binding.channel_type)

                    await adapter.send_message(
                        OutgoingMessage(
                            channel_id=binding.channel_id,
                            text=formatted,
                        )
                    )
                    delivered += 1

                except ValueError as exc:
                    # Channel not configured — skip silently
                    logger.debug(
                        "Channel %s not configured for notification to user %s: %s",
                        binding.channel_type, user_id, exc,
                    )
                except Exception as exc:
                    logger.warning(
                        "Failed to push notification to %s:%s for user %s: %s",
                        binding.channel_type, binding.channel_id, user_id, exc,
                    )

            if delivered:
                logger.info(
                    "Pushed '%s' notification to %d channel(s) for user %s",
                    category, delivered, user_id,
                )

    except Exception as exc:
        logger.error(
            "Notification bridge failed for user %s: %s",
            user_id, exc,
            exc_info=True,
        )


def _format_notification(category_label: str, title: str, body: str) -> str:
    """Format a notification into a channel-friendly text message."""
    lines = [
        f"[{category_label}] {title}",
        "",
        body,
    ]
    return "\n".join(lines)
