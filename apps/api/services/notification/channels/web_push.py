"""Web Push notification channel — delivers via VAPID / RFC 8030.

Uses the pywebpush library to send encrypted push messages to browser
push endpoints stored in the push_subscriptions table.
"""

import asyncio
import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.notification import Notification
from models.push_subscription import PushSubscription
from services.notification.channels import NotificationChannel, DeliveryResult

logger = logging.getLogger(__name__)


class WebPushChannel(NotificationChannel):
    """Delivers notifications via the Web Push Protocol (VAPID)."""

    name = "web_push"

    async def send(
        self,
        user_id: uuid.UUID,
        notification: Notification,
        db: AsyncSession,
    ) -> DeliveryResult:
        """Send push notification to all active subscriptions for this user."""
        if not settings.vapid_private_key or not settings.vapid_claims_email:
            return DeliveryResult(status="skipped", error="VAPID keys not configured")

        result = await db.execute(
            select(PushSubscription).where(
                PushSubscription.user_id == user_id,
                PushSubscription.is_active == True,
            )
        )
        subscriptions = result.scalars().all()

        if not subscriptions:
            return DeliveryResult(status="skipped", error="No active push subscriptions")

        payload = json.dumps({
            "title": notification.title,
            "body": notification.body,
            "category": notification.category,
            "notification_id": str(notification.id),
            "priority": notification.priority,
        })

        vapid_claims = {"sub": f"mailto:{settings.vapid_claims_email}"}
        sent_count = 0
        errors: list[str] = []

        for sub in subscriptions:
            try:
                from pywebpush import webpush, WebPushException

                subscription_info = {
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh_key,
                        "auth": sub.auth_key,
                    },
                }

                await asyncio.to_thread(
                    webpush,
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims=vapid_claims,
                )
                sent_count += 1

            except Exception as e:
                error_msg = str(e)
                errors.append(error_msg)

                # Handle 410 Gone — subscription expired, mark inactive
                is_gone = False
                try:
                    from pywebpush import WebPushException
                    if isinstance(e, WebPushException) and hasattr(e, "response"):
                        if e.response is not None and e.response.status_code == 410:
                            is_gone = True
                except Exception:
                    pass

                if is_gone or "410" in error_msg:
                    sub.is_active = False
                    await db.flush()
                    logger.info("Push subscription deactivated (410 Gone): %s", sub.endpoint[:60])
                else:
                    logger.warning("Web push failed for subscription %s: %s", sub.id, error_msg)

        if sent_count > 0:
            return DeliveryResult(status="sent")
        return DeliveryResult(status="failed", error="; ".join(errors))

    async def is_available(self, user_id: uuid.UUID, db: AsyncSession) -> bool:
        """Check if user has any active push subscriptions."""
        if not settings.vapid_private_key:
            return False

        result = await db.execute(
            select(PushSubscription.id).where(
                PushSubscription.user_id == user_id,
                PushSubscription.is_active == True,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None
