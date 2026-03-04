"""WhatsApp Cloud API messaging helpers — standalone functions for outbound messages.

Provides simple async functions for sending WhatsApp messages without requiring
the full BaseChannelAdapter lifecycle. Mirrors the Telegram helpers for:
- Study reminders from the scheduler
- Admin alerts and status messages
- Quick one-off notifications from any service

Uses WHATSAPP_PHONE_NUMBER_ID and WHATSAPP_ACCESS_TOKEN from environment / config.
Falls back gracefully when credentials are not configured.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)


@dataclass
class WhatsAppResult:
    """Result of a WhatsApp send operation."""

    success: bool
    error: str | None = None
    message_id: str | None = None


async def send_whatsapp_message(
    recipient: str,
    text: str,
    *,
    phone_number_id: str | None = None,
    access_token: str | None = None,
) -> WhatsAppResult:
    """Send a text message via the WhatsApp Cloud API.

    Args:
        recipient: Recipient phone number in international format (e.g. "15551234567").
        text: Message text to send.
        phone_number_id: WhatsApp Business phone number ID. Falls back to settings.
        access_token: Bearer token. Falls back to settings.whatsapp_access_token.

    Returns:
        WhatsAppResult with success status and optional error/message_id.
    """
    pid = phone_number_id or settings.whatsapp_phone_number_id
    token = access_token or settings.whatsapp_access_token

    if not pid:
        return WhatsAppResult(success=False, error="whatsapp_phone_number_id not configured")
    if not token:
        return WhatsAppResult(success=False, error="whatsapp_access_token not configured")
    if not recipient:
        return WhatsAppResult(success=False, error="recipient is required")
    if not text:
        return WhatsAppResult(success=False, error="text is required")

    url = f"{GRAPH_API_BASE}/{pid}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, json=body, headers=headers)

        if resp.status_code >= 400:
            error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.error("WhatsApp send_message failed: %s", error_msg)
            return WhatsAppResult(success=False, error=error_msg)

        msg_id = None
        try:
            messages = resp.json().get("messages", [])
            if messages:
                msg_id = messages[0].get("id")
        except Exception:
            pass

        logger.debug("WhatsApp message sent to %s (message_id=%s)", recipient, msg_id)
        return WhatsAppResult(success=True, message_id=msg_id)

    except httpx.TimeoutException as exc:
        error_msg = f"Request timed out: {exc}"
        logger.error("WhatsApp send_message timeout: %s", error_msg)
        return WhatsAppResult(success=False, error=error_msg)
    except httpx.HTTPError as exc:
        error_msg = f"HTTP error: {exc}"
        logger.error("WhatsApp send_message HTTP error: %s", error_msg)
        return WhatsAppResult(success=False, error=error_msg)


async def send_study_reminder(
    recipient: str | None,
    course_name: str,
    message: str,
) -> WhatsAppResult:
    """Send a formatted study reminder via WhatsApp.

    Args:
        recipient: Phone number. Falls back to first configured WhatsApp binding.
        course_name: Name of the course for context.
        message: The reminder message body.

    Returns:
        WhatsAppResult with success status.
    """
    if not recipient:
        return WhatsAppResult(success=False, error="No recipient provided")

    text = f"*Study Reminder*\n\n*Course:* {course_name}\n\n{message}"
    return await send_whatsapp_message(recipient, text)


async def send_notification_via_whatsapp(
    recipient: str | None,
    title: str,
    body: str,
    category: str = "notification",
) -> WhatsAppResult:
    """Send a generic notification formatted for WhatsApp.

    Used by the notification dispatcher when WhatsApp is an enabled channel.

    Args:
        recipient: Phone number. Required.
        title: Notification title.
        body: Notification body text.
        category: Notification category for the label prefix.

    Returns:
        WhatsAppResult with success status.
    """
    if not recipient:
        return WhatsAppResult(success=False, error="No recipient provided")

    category_labels = {
        "reminder": "Reminder",
        "weekly_prep": "Weekly Prep",
        "fsrs_review": "Review Due",
        "progress": "Progress Update",
        "progress_review": "Progress Review",
        "inactivity": "We Miss You",
        "goal": "Goal Update",
        "study_reminder": "Study Reminder",
    }
    label = category_labels.get(category, category.replace("_", " ").title())

    text = f"*[{label}] {title}*\n\n{body}"
    return await send_whatsapp_message(recipient, text)
