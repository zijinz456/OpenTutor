"""Telegram Bot API adapter for multi-channel messaging.

Implements BaseChannelAdapter for the Telegram Bot API.
Handles webhook verification, inbound message parsing, outbound message
delivery, media downloads, and typing indicators.

Docs: https://core.telegram.org/bots/api
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings
from services.channels.base import (
    BaseChannelAdapter,
    IncomingMessage,
    OutgoingMessage,
    _DEFAULT_TIMEOUT,
    encode_media_response,
    mime_to_extension,
)

logger = logging.getLogger(__name__)

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramAdapter(BaseChannelAdapter):
    """Telegram Bot API channel adapter."""

    channel_type = "telegram"

    # ── Webhook verification ──

    async def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        """Verify incoming Telegram webhook.

        Telegram does not sign webhook payloads with HMAC. Instead, security
        relies on keeping the webhook URL secret (contains the bot token path).
        The webhook endpoint itself should be served over HTTPS and the URL
        should not be publicly guessable.

        We accept all payloads when the bot token is configured, since Telegram
        guarantees delivery only to the registered webhook URL.

        Args:
            payload: Raw request body bytes (not used for verification).
            headers: HTTP headers (keys should be lowercase).

        Returns:
            True if the bot token is configured (webhook presumed authentic).
        """
        if not settings.telegram_bot_token:
            logger.warning("telegram_bot_token not configured — rejecting webhook")
            return False
        return True

    # ── Inbound message parsing ──

    async def parse_webhook(
        self, payload: dict, headers: dict
    ) -> IncomingMessage | None:
        """Parse a Telegram Update into an IncomingMessage.

        Telegram webhook (Update) structure::

            {
              "update_id": 123456,
              "message": {
                "message_id": 42,
                "from": {"id": 123, "first_name": "Alice", "username": "alice"},
                "chat": {"id": 123, "type": "private"},
                "date": 1700000000,
                "text": "Hello"
              }
            }

        Supports text messages and photo messages. Returns None for non-message
        updates (inline queries, callback queries, channel posts, etc.).
        """
        try:
            message = payload.get("message")
            if not message:
                # Could be an edited_message, channel_post, callback_query, etc.
                logger.debug("Telegram update has no 'message' field — ignoring")
                return None

            chat = message.get("chat", {})
            chat_id = chat.get("id")
            chat_type = chat.get("type", "private")
            sender = message.get("from", {})
            sender_id = sender.get("id")
            message_id = message.get("message_id")
            timestamp = float(message.get("date", 0))

            if not chat_id or not sender_id:
                return None

            # Extract text content
            text = message.get("text", "")

            # Caption for media messages
            if not text:
                text = message.get("caption", "") or ""

            # Extract media references (photos, documents)
            media: list[dict] = []

            # Photos: Telegram sends an array of PhotoSize objects (different
            # resolutions). We take the largest one (last in the array).
            photos = message.get("photo")
            if photos:
                largest = photos[-1]
                media.append({
                    "type": "image",
                    "media_id": largest.get("file_id", ""),
                    "mime_type": "image/jpeg",  # Telegram photos are always JPEG
                    "file_unique_id": largest.get("file_unique_id", ""),
                })

            # Documents
            document = message.get("document")
            if document:
                media.append({
                    "type": "document",
                    "media_id": document.get("file_id", ""),
                    "mime_type": document.get("mime_type", "application/octet-stream"),
                    "filename": document.get("file_name", ""),
                    "file_unique_id": document.get("file_unique_id", ""),
                })

            # Voice messages
            voice = message.get("voice")
            if voice:
                media.append({
                    "type": "audio",
                    "media_id": voice.get("file_id", ""),
                    "mime_type": voice.get("mime_type", "audio/ogg"),
                    "file_unique_id": voice.get("file_unique_id", ""),
                })

            # Skip if no text and no supported media
            if not text and not media:
                logger.debug("Telegram message has no text or supported media — ignoring")
                return None

            # Use chat_id as the channel_id (string form)
            is_group = chat_type in ("group", "supergroup")

            return IncomingMessage(
                channel_type=self.channel_type,
                channel_id=str(chat_id),
                message_id=str(message_id),
                text=text,
                media=media,
                timestamp=timestamp,
                raw_payload=payload,
                is_group=is_group,
                group_id=str(chat_id) if is_group else None,
            )

        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.error("Failed to parse Telegram webhook: %s", exc, exc_info=True)
            return None

    # ── Outbound messaging ──

    async def send_message(self, message: OutgoingMessage) -> bool:
        """Send a text message via the Telegram Bot API.

        POST https://api.telegram.org/bot{token}/sendMessage

        Args:
            message: The outgoing message to send.

        Returns:
            True if the API responded with a 2xx status.
        """
        bot_token = settings.telegram_bot_token
        if not bot_token:
            logger.error("Telegram send_message failed: telegram_bot_token not configured")
            return False

        url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
        body: dict[str, Any] = {
            "chat_id": message.channel_id,
            "text": message.text,
            "parse_mode": "Markdown",
        }

        # Add reply_to_message_id if specified
        if message.reply_to_message_id:
            body["reply_to_message_id"] = message.reply_to_message_id

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, json=body)

            if resp.status_code >= 400:
                # If Markdown parse fails, retry without parse_mode
                if resp.status_code == 400 and "parse" in resp.text.lower():
                    logger.debug("Telegram Markdown parse failed, retrying as plain text")
                    body.pop("parse_mode", None)
                    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                        resp = await client.post(url, json=body)
                    if resp.status_code < 400:
                        logger.debug("Telegram message sent (plain text) to %s", message.channel_id)
                        return True

                logger.error(
                    "Telegram send_message failed: HTTP %d — %s",
                    resp.status_code,
                    resp.text,
                )
                return False

            logger.debug("Telegram message sent to %s", message.channel_id)
            return True

        except httpx.HTTPError as exc:
            logger.error("Telegram send_message HTTP error: %s", exc)
            return False

    # ── Media download ──

    async def download_media(
        self, media_url: str | None, media_id: str | None
    ) -> dict | None:
        """Download media from Telegram and return base64-encoded content.

        Telegram media download is a two-step process:
        1. GET ``/bot{token}/getFile`` with ``file_id`` to obtain the file path.
        2. GET ``https://api.telegram.org/file/bot{token}/{file_path}`` to
           download the binary data.

        Args:
            media_url: Direct URL to the media (if available).
            media_id: Telegram file_id from the webhook payload.

        Returns:
            Dict with ``data`` (base64), ``mime_type``, and ``filename`` keys,
            or None on failure.
        """
        bot_token = settings.telegram_bot_token
        if not bot_token:
            logger.error("Telegram download_media: bot token not configured")
            return None

        if not media_id and not media_url:
            logger.warning("Telegram download_media called without media_id or media_url")
            return None

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                if media_url:
                    resp = await client.get(media_url)
                else:
                    # Step 1: Get file path via getFile API
                    file_url = f"{TELEGRAM_API_BASE}/bot{bot_token}/getFile"
                    file_resp = await client.get(file_url, params={"file_id": media_id})

                    if file_resp.status_code != 200:
                        logger.error(
                            "Telegram getFile failed: HTTP %d — %s",
                            file_resp.status_code,
                            file_resp.text,
                        )
                        return None

                    file_data = file_resp.json().get("result", {})
                    file_path = file_data.get("file_path", "")
                    if not file_path:
                        logger.error("Telegram getFile response missing file_path")
                        return None

                    # Step 2: Download the actual file
                    download_url = f"{TELEGRAM_API_BASE}/file/bot{bot_token}/{file_path}"
                    resp = await client.get(download_url)

                if resp.status_code != 200:
                    logger.error(
                        "Telegram media download failed: HTTP %d",
                        resp.status_code,
                    )
                    return None

                result = encode_media_response(resp)
                if result and media_id:
                    ext = mime_to_extension(result["mime_type"])
                    result["filename"] = f"telegram_{media_id[:12]}{ext}"
                return result

        except httpx.HTTPError as exc:
            logger.error("Telegram download_media HTTP error: %s", exc)
            return None

    # ── Typing indicator ──

    async def send_typing_indicator(self, channel_id: str) -> None:
        """Send a 'typing' chat action via the Telegram Bot API.

        POST /bot{token}/sendChatAction with action=typing

        Args:
            channel_id: The chat ID to show typing in.
        """
        bot_token = settings.telegram_bot_token
        if not bot_token:
            return

        url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendChatAction"
        body = {
            "chat_id": channel_id,
            "action": "typing",
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                await client.post(url, json=body)
        except httpx.HTTPError as exc:
            # Typing indicators are best-effort
            logger.debug("Telegram typing indicator failed: %s", exc)
