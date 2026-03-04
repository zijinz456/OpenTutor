"""WhatsApp notification channel — delivers notifications via WhatsApp Cloud API.

Plugs into the notification dispatcher's channel registry, enabling WhatsApp
as a delivery backend alongside SSE, WebPush, and Telegram.

Requires WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN in .env.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.channel_binding import ChannelBinding
from models.notification import Notification
from services.notification.channels import NotificationChannel, DeliveryResult

logger = logging.getLogger(__name__)


class WhatsAppChannel(NotificationChannel):
    """Delivers notifications to WhatsApp via the Cloud API."""

    name = "whatsapp"

    async def send(
        self,
        user_id: uuid.UUID,
        notification: Notification,
        db: AsyncSession,
    ) -> DeliveryResult:
        """Send a notification to the user's WhatsApp number.

        Resolution order for recipient:
        1. ChannelBinding with channel_type="whatsapp" for this user
        2. No default fallback (unlike Telegram, WhatsApp requires explicit binding)

        Returns DeliveryResult with status "sent", "failed", or "skipped".
        """
        if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
            return DeliveryResult(
                status="skipped",
                error="WhatsApp credentials not configured",
            )

        recipient = await self._resolve_recipient(user_id, db)
        if not recipient:
            return DeliveryResult(
                status="skipped",
                error="No WhatsApp binding found for user",
            )

        from services.messaging.whatsapp import send_notification_via_whatsapp

        result = await send_notification_via_whatsapp(
            recipient=recipient,
            title=notification.title,
            body=notification.body,
            category=notification.category,
        )

        if result.success:
            return DeliveryResult(status="sent")
        return DeliveryResult(status="failed", error=result.error)

    async def is_available(self, user_id: uuid.UUID, db: AsyncSession) -> bool:
        """Check if WhatsApp delivery is possible for this user.

        Returns True if:
        - WhatsApp credentials are configured, AND
        - The user has a WhatsApp channel binding.
        """
        if not settings.whatsapp_phone_number_id or not settings.whatsapp_access_token:
            return False

        result = await db.execute(
            select(ChannelBinding.id).where(
                ChannelBinding.user_id == user_id,
                ChannelBinding.channel_type == "whatsapp",
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _resolve_recipient(
        self, user_id: uuid.UUID, db: AsyncSession
    ) -> str | None:
        """Resolve the WhatsApp phone number for a given user."""
        result = await db.execute(
            select(ChannelBinding.channel_id).where(
                ChannelBinding.user_id == user_id,
                ChannelBinding.channel_type == "whatsapp",
            ).limit(1)
        )
        return result.scalar_one_or_none()
