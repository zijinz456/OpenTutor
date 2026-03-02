"""Telegram Bot API messaging helpers — standalone functions for outbound messages.

Provides simple async functions for sending Telegram messages without requiring
the full BaseChannelAdapter lifecycle. Useful for:
- Study reminders from the scheduler
- Admin alerts and status messages
- Quick one-off notifications from any service

Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment / config.
Falls back gracefully when credentials are not configured.

Docs: https://core.telegram.org/bots/api#sendmessage
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"

_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)


@dataclass
class TelegramResult:
    """Result of a Telegram send operation."""

    success: bool
    error: str | None = None
    message_id: int | None = None


async def send_telegram_message(
    chat_id: str,
    text: str,
    token: str | None = None,
    *,
    parse_mode: str = "Markdown",
) -> TelegramResult:
    """Send a text message via the Telegram Bot API.

    Args:
        chat_id: Telegram chat ID (user, group, or channel).
        text: Message text to send.
        token: Bot token. Falls back to settings.telegram_bot_token if not provided.
        parse_mode: Telegram parse mode ("Markdown", "HTML", or None for plain text).

    Returns:
        TelegramResult with success status and optional error/message_id.
    """
    bot_token = token or settings.telegram_bot_token
    if not bot_token:
        return TelegramResult(
            success=False,
            error="telegram_bot_token not configured",
        )

    if not chat_id:
        return TelegramResult(success=False, error="chat_id is required")

    if not text:
        return TelegramResult(success=False, error="text is required")

    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    body: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        body["parse_mode"] = parse_mode

    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(url, json=body)

        if resp.status_code >= 400:
            # If Markdown parse fails, retry as plain text
            if resp.status_code == 400 and parse_mode and "parse" in resp.text.lower():
                logger.debug("Telegram Markdown parse failed, retrying as plain text")
                body.pop("parse_mode", None)
                async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                    resp = await client.post(url, json=body)
                if resp.status_code < 400:
                    msg_id = resp.json().get("result", {}).get("message_id")
                    return TelegramResult(success=True, message_id=msg_id)

            error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            logger.error("Telegram send_message failed: %s", error_msg)
            return TelegramResult(success=False, error=error_msg)

        msg_id = resp.json().get("result", {}).get("message_id")
        logger.debug("Telegram message sent to %s (message_id=%s)", chat_id, msg_id)
        return TelegramResult(success=True, message_id=msg_id)

    except httpx.TimeoutException as exc:
        error_msg = f"Request timed out: {exc}"
        logger.error("Telegram send_message timeout: %s", error_msg)
        return TelegramResult(success=False, error=error_msg)
    except httpx.HTTPError as exc:
        error_msg = f"HTTP error: {exc}"
        logger.error("Telegram send_message HTTP error: %s", error_msg)
        return TelegramResult(success=False, error=error_msg)


async def send_study_reminder(
    chat_id: str | None,
    course_name: str,
    message: str,
    token: str | None = None,
) -> TelegramResult:
    """Send a formatted study reminder via Telegram.

    Formats the message with a study-themed header and course context.
    Uses the default chat_id from settings if none is provided.

    Args:
        chat_id: Telegram chat ID. Falls back to settings.telegram_chat_id.
        course_name: Name of the course for context.
        message: The reminder message body.
        token: Bot token override.

    Returns:
        TelegramResult with success status.
    """
    target_chat = chat_id or settings.telegram_chat_id
    if not target_chat:
        return TelegramResult(
            success=False,
            error="No chat_id provided and telegram_chat_id not configured",
        )

    # Build formatted reminder text
    lines = [
        "*Study Reminder*",
        "",
        f"*Course:* {_escape_markdown(course_name)}",
        "",
        _escape_markdown(message),
    ]
    text = "\n".join(lines)

    return await send_telegram_message(target_chat, text, token)


async def send_notification_via_telegram(
    chat_id: str | None,
    title: str,
    body: str,
    category: str = "notification",
    token: str | None = None,
) -> TelegramResult:
    """Send a generic notification formatted for Telegram.

    Used by the notification dispatcher when Telegram is an enabled channel.

    Args:
        chat_id: Telegram chat ID. Falls back to settings.telegram_chat_id.
        title: Notification title.
        body: Notification body text.
        category: Notification category for the label prefix.
        token: Bot token override.

    Returns:
        TelegramResult with success status.
    """
    target_chat = chat_id or settings.telegram_chat_id
    if not target_chat:
        return TelegramResult(
            success=False,
            error="No chat_id provided and telegram_chat_id not configured",
        )

    # Category label mapping
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

    lines = [
        f"*[{_escape_markdown(label)}] {_escape_markdown(title)}*",
        "",
        _escape_markdown(body),
    ]
    text = "\n".join(lines)

    return await send_telegram_message(target_chat, text, token)


def _escape_markdown(text: str) -> str:
    """Escape special Markdown V1 characters in text.

    Telegram Markdown V1 uses * _ ` [ as formatting characters.
    We escape them to prevent accidental formatting in user-provided text.
    Preserves intentional formatting already in the template strings.
    """
    # Only escape underscores and backticks in user text —
    # asterisks are used intentionally in our templates
    for char in ("_", "`", "["):
        text = text.replace(char, f"\\{char}")
    return text
