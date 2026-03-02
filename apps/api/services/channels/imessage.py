"""BlueBubbles iMessage adapter for multi-channel messaging.

Implements BaseChannelAdapter for the BlueBubbles REST API, which bridges
macOS iMessage to HTTP.  Supports both webhook-based and polling-based
message ingestion for environments where webhooks are not reachable.

Docs: https://bluebubbles.app/docs/
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any, Callable, Coroutine

import httpx

from config import settings
from services.channels.base import BaseChannelAdapter, IncomingMessage, OutgoingMessage

logger = logging.getLogger(__name__)

# Reusable client timeout
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)


class IMessageAdapter(BaseChannelAdapter):
    """BlueBubbles iMessage channel adapter."""

    channel_type = "imessage"

    # ── Webhook verification ──

    async def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        """Verify incoming webhook authenticity via shared secret.

        BlueBubbles uses a simple shared-secret header ``X-BlueBubbles-Secret``
        for webhook authentication.

        Args:
            payload: Raw request body bytes (not used for verification).
            headers: HTTP headers (keys should be lowercase).

        Returns:
            True if the secret matches the configured value.
        """
        webhook_secret = settings.bluebubbles_webhook_secret
        if not webhook_secret:
            logger.warning(
                "bluebubbles_webhook_secret not configured — rejecting webhook"
            )
            return False

        provided_secret = headers.get("x-bluebubbles-secret", "")
        if not provided_secret:
            logger.debug("Missing X-BlueBubbles-Secret header")
            return False

        # Constant-time comparison to avoid timing attacks
        import hmac as _hmac

        return _hmac.compare_digest(provided_secret, webhook_secret)

    # ── Inbound message parsing ──

    async def parse_webhook(
        self, payload: dict, headers: dict
    ) -> IncomingMessage | None:
        """Parse a BlueBubbles webhook into an IncomingMessage.

        BlueBubbles webhook structure for new messages::

            {
              "type": "new-message",
              "data": {
                "guid": "iMessage;-;guid-here",
                "text": "Hello there",
                "isFromMe": false,
                "handle": {
                  "address": "+15551234567"
                },
                "dateCreated": 1700000000000,
                "attachments": [
                  {
                    "guid": "att-guid",
                    "mimeType": "image/jpeg",
                    "transferName": "photo.jpg",
                    "totalBytes": 12345
                  }
                ]
              }
            }

        Returns None for non-message events (typing indicators, read receipts,
        group-name changes, messages sent by the local user, etc.).
        """
        try:
            event_type = payload.get("type", "")
            if event_type != "new-message":
                logger.debug("Ignoring BlueBubbles event type: %s", event_type)
                return None

            data = payload.get("data", {})
            if not data:
                return None

            # Skip messages sent by the local Mac user
            if data.get("isFromMe", True):
                return None

            # Extract sender handle (address)
            handle = data.get("handle")
            if isinstance(handle, dict):
                sender = handle.get("address", "")
            elif isinstance(handle, str):
                sender = handle
            else:
                logger.warning("BlueBubbles message missing handle information")
                return None

            if not sender:
                return None

            message_id = data.get("guid", "")
            text = data.get("text", "") or ""

            # Timestamp: BlueBubbles uses milliseconds since epoch
            date_created = data.get("dateCreated", 0)
            timestamp = float(date_created) / 1000.0 if date_created else time.time()

            # Extract attachments
            media: list[dict] = []
            attachments = data.get("attachments", [])
            for att in attachments:
                att_guid = att.get("guid", "")
                mime_type = att.get("mimeType", "application/octet-stream")
                filename = att.get("transferName", "")
                total_bytes = att.get("totalBytes", 0)

                # Determine media type from MIME
                if mime_type.startswith("image/"):
                    media_type = "image"
                elif mime_type.startswith("audio/"):
                    media_type = "audio"
                elif mime_type.startswith("video/"):
                    media_type = "video"
                else:
                    media_type = "document"

                media.append({
                    "type": media_type,
                    "media_id": att_guid,
                    "mime_type": mime_type,
                    "filename": filename,
                    "total_bytes": total_bytes,
                })

            # Detect group conversations
            chats = data.get("chats") or []
            chat_guid = chats[0].get("guid", "") if chats else ""
            is_group = ";+;" in chat_guid if chat_guid else False

            return IncomingMessage(
                channel_type=self.channel_type,
                channel_id=sender,
                message_id=message_id,
                text=text,
                media=media,
                timestamp=timestamp,
                raw_payload=payload,
                is_group=is_group,
                group_id=chat_guid if is_group else None,
            )

        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.error(
                "Failed to parse BlueBubbles webhook: %s", exc, exc_info=True
            )
            return None

    # ── Outbound messaging ──

    async def send_message(self, message: OutgoingMessage) -> bool:
        """Send a text message via the BlueBubbles API.

        POST {server_url}/api/v1/message/text?password={password}

        The body contains the chat GUID (``iMessage;-;{address}``) and the
        message text.

        Args:
            message: The outgoing message to send.

        Returns:
            True if the API responded successfully.
        """
        server_url = settings.bluebubbles_server_url.rstrip("/")
        password = settings.bluebubbles_password

        if not server_url or not password:
            logger.error(
                "iMessage send_message failed: bluebubbles_server_url or "
                "bluebubbles_password not configured"
            )
            return False

        url = f"{server_url}/api/v1/message/text"
        params = {"password": password}

        # Build the chat GUID.  Individual chats use "iMessage;-;{address}".
        # If the channel_id already looks like a chat GUID, use it as-is.
        if message.channel_id.startswith("iMessage;") or message.channel_id.startswith("SMS;"):
            chat_guid = message.channel_id
        else:
            chat_guid = f"iMessage;-;{message.channel_id}"

        body: dict[str, Any] = {
            "chatGuid": chat_guid,
            "message": message.text,
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, json=body, params=params)

            if resp.status_code >= 400:
                logger.error(
                    "iMessage send_message failed: HTTP %d — %s",
                    resp.status_code,
                    resp.text,
                )
                return False

            logger.debug("iMessage sent to %s", message.channel_id)
            return True

        except httpx.HTTPError as exc:
            logger.error("iMessage send_message HTTP error: %s", exc)
            return False

    # ── Media download ──

    async def download_media(
        self, media_url: str | None, media_id: str | None
    ) -> dict | None:
        """Download an attachment from BlueBubbles and return base64-encoded content.

        BlueBubbles serves attachment data at::

            GET {server_url}/api/v1/attachment/{guid}/download?password={password}

        Args:
            media_url: Optional direct URL (used if provided, otherwise built
                       from media_id).
            media_id: BlueBubbles attachment GUID.

        Returns:
            Dict with ``data`` (base64), ``mime_type``, and ``filename`` keys,
            or None on failure.
        """
        server_url = settings.bluebubbles_server_url.rstrip("/")
        password = settings.bluebubbles_password

        if not server_url or not password:
            logger.error("iMessage download_media: server_url or password not configured")
            return None

        if media_url:
            # If a direct URL is provided, use it (may already include auth)
            download_url = media_url
            params: dict[str, str] = {}
            if password and "password=" not in media_url:
                params["password"] = password
        elif media_id:
            download_url = f"{server_url}/api/v1/attachment/{media_id}/download"
            params = {"password": password}
        else:
            logger.warning("iMessage download_media called without media_url or media_id")
            return None

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(download_url, params=params)

            if resp.status_code != 200:
                logger.error(
                    "iMessage media download failed: HTTP %d — %s",
                    resp.status_code,
                    resp.text[:200] if resp.text else "",
                )
                return None

            # Determine MIME type from Content-Type header
            content_type = resp.headers.get("content-type", "application/octet-stream")
            mime_type = content_type.split(";")[0].strip()

            encoded = base64.b64encode(resp.content).decode("utf-8")

            # Try to derive a filename
            filename = ""
            content_disp = resp.headers.get("content-disposition", "")
            if "filename=" in content_disp:
                filename = content_disp.split("filename=")[-1].strip('" ')
            if not filename and media_id:
                ext = _mime_to_extension(mime_type)
                filename = f"imessage_{media_id[:12]}{ext}"

            return {
                "data": encoded,
                "mime_type": mime_type,
                "filename": filename,
            }

        except httpx.HTTPError as exc:
            logger.error("iMessage download_media HTTP error: %s", exc)
            return None

    # ── Typing indicator ──

    async def send_typing_indicator(self, channel_id: str) -> None:
        """No-op: BlueBubbles does not support sending typing indicators."""
        pass


# ── Polling mode ──

# Module-level flag to allow clean shutdown of the polling loop.
_polling_active = False
_polling_task: asyncio.Task | None = None


async def start_polling(
    interval: float = 5.0,
    on_message: Callable[[IncomingMessage], Coroutine] | None = None,
) -> None:
    """Poll BlueBubbles for new messages when webhooks are not configured.

    This is useful for development environments or networks where the
    BlueBubbles server is not publicly reachable for webhook delivery.

    The function starts an asyncio background task that polls the
    BlueBubbles ``/api/v1/message`` endpoint at the given interval.

    Args:
        interval: Seconds between poll cycles (default 5.0).
        on_message: Async callback invoked for each new IncomingMessage.
                    If None, messages are dispatched through the standard
                    ``dispatch_message`` pipeline.
    """
    global _polling_active, _polling_task

    server_url = settings.bluebubbles_server_url.rstrip("/")
    password = settings.bluebubbles_password

    if not server_url or not password:
        logger.error(
            "Cannot start iMessage polling: bluebubbles_server_url or "
            "bluebubbles_password not configured"
        )
        return

    if _polling_active:
        logger.warning("iMessage polling is already active")
        return

    _polling_active = True
    adapter = IMessageAdapter()

    # Resolve the message handler
    if on_message is None:
        from services.channels.dispatcher import dispatch_message
        from database import async_session as _db_factory

        async def _default_handler(msg: IncomingMessage) -> None:
            async with _db_factory() as _db:
                await dispatch_message(adapter, msg, _db, _db_factory)

        handler = _default_handler
    else:
        handler = on_message

    async def _poll_loop() -> None:
        """Internal polling loop — runs until stop_polling() is called."""
        # Track the last seen message timestamp to avoid reprocessing
        last_timestamp_ms = int(time.time() * 1000)
        seen_guids: set[str] = set()
        # Cap the seen set to avoid unbounded memory growth
        max_seen = 10_000

        logger.info(
            "iMessage polling started (interval=%.1fs, server=%s)",
            interval,
            server_url,
        )

        while _polling_active:
            try:
                url = f"{server_url}/api/v1/message"
                params = {
                    "password": password,
                    "after": str(last_timestamp_ms),
                    "limit": "50",
                    "sort": "ASC",
                    "with": "handle,attachments,chats",
                }

                async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                    resp = await client.get(url, params=params)

                if resp.status_code != 200:
                    logger.warning(
                        "iMessage poll failed: HTTP %d",
                        resp.status_code,
                    )
                    await asyncio.sleep(interval)
                    continue

                data = resp.json()
                messages = data.get("data", [])

                for msg_data in messages:
                    guid = msg_data.get("guid", "")

                    # Deduplicate
                    if guid in seen_guids:
                        continue
                    seen_guids.add(guid)

                    # Prune seen set if it grows too large — keep recent half
                    if len(seen_guids) > max_seen:
                        keep = list(seen_guids)[max_seen // 2:]
                        seen_guids.clear()
                        seen_guids.update(keep)

                    # Skip messages from self
                    if msg_data.get("isFromMe", True):
                        continue

                    # Update watermark
                    date_created = msg_data.get("dateCreated", 0)
                    if date_created > last_timestamp_ms:
                        last_timestamp_ms = date_created

                    # Build a synthetic webhook payload and parse it
                    synthetic_payload = {
                        "type": "new-message",
                        "data": msg_data,
                    }
                    incoming = await adapter.parse_webhook(synthetic_payload, {})
                    if incoming:
                        try:
                            await handler(incoming)
                        except Exception as exc:
                            logger.error(
                                "iMessage poll handler error for %s: %s",
                                guid,
                                exc,
                                exc_info=True,
                            )

            except asyncio.CancelledError:
                logger.info("iMessage polling cancelled")
                break
            except Exception as exc:
                logger.error(
                    "iMessage poll loop error: %s", exc, exc_info=True
                )

            await asyncio.sleep(interval)

        logger.info("iMessage polling stopped")

    _polling_task = asyncio.create_task(_poll_loop())


async def stop_polling() -> None:
    """Gracefully stop the iMessage polling loop."""
    global _polling_active, _polling_task

    _polling_active = False
    if _polling_task and not _polling_task.done():
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass
    _polling_task = None
    logger.info("iMessage polling shut down")


# ── Helpers ──

def _mime_to_extension(mime_type: str) -> str:
    """Map common MIME types to file extensions."""
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/heic": ".heic",
        "image/tiff": ".tiff",
        "audio/mp4": ".m4a",
        "audio/mpeg": ".mp3",
        "audio/aac": ".aac",
        "audio/caf": ".caf",
        "video/mp4": ".mp4",
        "video/quicktime": ".mov",
        "application/pdf": ".pdf",
    }
    return mapping.get(mime_type, "")
