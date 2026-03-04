"""Notification dispatcher — central orchestration for multi-channel delivery.

Handles dedup, quiet hours, frequency caps, channel routing, and delivery
tracking in a single dispatch() call used by all notification producers.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta, time

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.notification import Notification
from models.notification_settings import NotificationSettings
from models.notification_delivery import NotificationDelivery
from services.notification.dedup import check_dedup
from services.notification.channels import NotificationChannel
from services.notification.channels.sse import SSEChannel
from services.notification.channels.web_push import WebPushChannel
from services.notification.channels.telegram import TelegramChannel

logger = logging.getLogger(__name__)

# Registry of all available notification channels
_CHANNEL_REGISTRY: dict[str, NotificationChannel] = {
    "sse": SSEChannel(),
    "web_push": WebPushChannel(),
    "telegram": TelegramChannel(),
}


async def get_or_create_settings(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> NotificationSettings:
    """Load notification settings for a user, creating defaults if none exist."""
    result = await db.execute(
        select(NotificationSettings).where(NotificationSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if settings is None:
        settings = NotificationSettings(user_id=user_id)
        db.add(settings)
        await db.flush()
        logger.debug("Created default notification settings for user %s", user_id)

    return settings


def _is_quiet_hours(ns: NotificationSettings) -> bool:
    """Check if the current time falls within the user's quiet hours window.

    Handles overnight ranges like 22:00–08:00 correctly.
    """
    if not ns.quiet_hours_start or not ns.quiet_hours_end:
        return False

    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(ns.timezone)
    except Exception:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("UTC")

    now = datetime.now(tz).time()

    try:
        start = time.fromisoformat(ns.quiet_hours_start)
        end = time.fromisoformat(ns.quiet_hours_end)
    except ValueError:
        logger.warning("Invalid quiet hours format: %s–%s", ns.quiet_hours_start, ns.quiet_hours_end)
        return False

    if start <= end:
        # Same-day range: e.g. 09:00–17:00
        return start <= now <= end
    else:
        # Overnight range: e.g. 22:00–08:00
        return now >= start or now <= end


async def _check_frequency_cap(
    user_id: uuid.UUID,
    ns: NotificationSettings,
    db: AsyncSession,
) -> bool:
    """Check if frequency caps have been exceeded.

    Returns True if sending is allowed, False if cap exceeded.
    """
    now = datetime.now(timezone.utc)

    # Hourly cap
    hour_ago = now - timedelta(hours=1)
    hourly_result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.created_at >= hour_ago,
        )
    )
    hourly_count = hourly_result.scalar() or 0

    if hourly_count >= ns.max_notifications_per_hour:
        logger.info(
            "Hourly frequency cap reached for user %s (%d/%d)",
            user_id, hourly_count, ns.max_notifications_per_hour,
        )
        return False

    # Daily cap
    day_ago = now - timedelta(days=1)
    daily_result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.created_at >= day_ago,
        )
    )
    daily_count = daily_result.scalar() or 0

    if daily_count >= ns.max_notifications_per_day:
        logger.info(
            "Daily frequency cap reached for user %s (%d/%d)",
            user_id, daily_count, ns.max_notifications_per_day,
        )
        return False

    return True


async def dispatch(
    user_id: uuid.UUID,
    title: str,
    body: str,
    category: str,
    *,
    course_id: uuid.UUID | None = None,
    priority: str = "normal",
    dedup_key: str | None = None,
    batch_key: str | None = None,
    scheduled_for: datetime | None = None,
    action_url: str | None = None,
    action_label: str | None = None,
    metadata_json: dict | None = None,
    db: AsyncSession,
) -> Notification | None:
    """Central notification dispatch — dedup, cap, route, deliver, track.

    Returns the created Notification, or None if skipped (dedup/cap/quiet hours).
    """
    # 1. Dedup check
    if dedup_key:
        if await check_dedup(dedup_key, db):
            logger.debug("Notification deduped: %s", dedup_key)
            return None

    # 2. Load user's notification settings
    ns = await get_or_create_settings(user_id, db)

    deliver_now = True
    if priority != "urgent":
        if _is_quiet_hours(ns):
            logger.info("Quiet hours active for user %s, notification will be saved without delivery", user_id)
            deliver_now = False
        elif not await _check_frequency_cap(user_id, ns, db):
            logger.info("Frequency cap exceeded for user %s, notification will be saved without delivery", user_id)
            deliver_now = False

    # 3. Create notification record after policy checks so the new row does not
    # count against the current frequency window.
    notification = Notification(
        user_id=user_id,
        course_id=course_id,
        title=title,
        body=body,
        category=category,
        priority=priority,
        dedup_key=dedup_key,
        batch_key=batch_key,
        scheduled_for=scheduled_for,
        action_url=action_url,
        action_label=action_label,
        metadata_json=metadata_json,
    )
    db.add(notification)
    await db.flush()

    if not deliver_now:
        await db.commit()
        return notification

    # 4. Deliver through enabled channels
    channels_used: list[str] = []
    enabled_channels = ns.channels_enabled if ns.channels_enabled is not None else ["sse"]

    for channel_name in enabled_channels:
        channel = _CHANNEL_REGISTRY.get(channel_name)
        if channel is None:
            logger.warning("Unknown notification channel: %s", channel_name)
            continue

        # Check channel availability
        if not await channel.is_available(user_id, db):
            delivery = NotificationDelivery(
                notification_id=notification.id,
                channel=channel_name,
                status="skipped",
                error_message="Channel not available for user",
            )
            db.add(delivery)
            continue

        # Attempt delivery
        result = await channel.send(user_id, notification, db)
        now = datetime.now(timezone.utc)

        delivery = NotificationDelivery(
            notification_id=notification.id,
            channel=channel_name,
            status=result.status,
            sent_at=now if result.status == "sent" else None,
            error_message=result.error,
        )
        db.add(delivery)

        if result.status == "sent":
            channels_used.append(channel_name)
            logger.debug("Notification delivered via %s to user %s", channel_name, user_id)

    # 5. Record which channels were used
    notification.sent_via = channels_used if channels_used else None
    await db.commit()

    logger.info(
        "Notification dispatched: [%s] %s → user %s via %s",
        category, title[:50], user_id, channels_used or "none",
    )

    return notification
