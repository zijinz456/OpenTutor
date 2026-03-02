"""Telegram notification channel — delivers notifications via the Telegram Bot API.

Plugs into the notification dispatcher's channel registry, enabling Telegram
as a delivery backend alongside SSE and WebPush. Notifications are delivered
to users who have a Telegram channel binding, or to the default chat_id
configured via TELEGRAM_CHAT_ID.

Requires TELEGRAM_BOT_TOKEN (and optionally TELEGRAM_CHAT_ID) in .env.
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


class TelegramChannel(NotificationChannel):
    """Delivers notifications to Telegram via the Bot API."""

    name = "telegram"

    async def send(
        self,
        user_id: uuid.UUID,
        notification: Notification,
        db: AsyncSession,
    ) -> DeliveryResult:
        """Send a notification to the user's Telegram chat.

        Resolution order for chat_id:
        1. ChannelBinding with channel_type="telegram" for this user
        2. Default telegram_chat_id from settings

        Returns DeliveryResult with status "sent", "failed", or "skipped".
        """
        if not settings.telegram_bot_token:
            return DeliveryResult(status="skipped", error="telegram_bot_token not configured")

        # Resolve the target chat_id
        chat_id = await self._resolve_chat_id(user_id, db)
        if not chat_id:
            return DeliveryResult(
                status="skipped",
                error="No Telegram chat_id found for user and no default configured",
            )

        # Send via the standalone messaging helper
        from services.messaging.telegram import send_notification_via_telegram

        result = await send_notification_via_telegram(
            chat_id=chat_id,
            title=notification.title,
            body=notification.body,
            category=notification.category,
        )

        if result.success:
            return DeliveryResult(status="sent")
        return DeliveryResult(status="failed", error=result.error)

    async def is_available(self, user_id: uuid.UUID, db: AsyncSession) -> bool:
        """Check if Telegram delivery is possible for this user.

        Returns True if:
        - The bot token is configured, AND
        - The user has a Telegram channel binding OR a default chat_id is set.
        """
        if not settings.telegram_bot_token:
            return False

        # Check for user-specific binding
        result = await db.execute(
            select(ChannelBinding.id).where(
                ChannelBinding.user_id == user_id,
                ChannelBinding.channel_type == "telegram",
            ).limit(1)
        )
        if result.scalar_one_or_none() is not None:
            return True

        # Fall back to default chat_id
        return bool(settings.telegram_chat_id)

    async def _resolve_chat_id(
        self, user_id: uuid.UUID, db: AsyncSession
    ) -> str | None:
        """Resolve the Telegram chat_id for a given user.

        Checks ChannelBinding first, then falls back to settings.telegram_chat_id.
        """
        result = await db.execute(
            select(ChannelBinding.channel_id).where(
                ChannelBinding.user_id == user_id,
                ChannelBinding.channel_type == "telegram",
            ).limit(1)
        )
        binding_chat_id = result.scalar_one_or_none()
        if binding_chat_id:
            return binding_chat_id

        return settings.telegram_chat_id or None
