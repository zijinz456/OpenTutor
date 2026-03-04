"""WhatsApp Cloud API adapter for multi-channel messaging.

Implements BaseChannelAdapter for the Meta WhatsApp Business Cloud API (v21.0).
Handles webhook verification (HMAC-SHA256), inbound message parsing, outbound
message delivery, media downloads, and typing indicators.

Docs: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from typing import Any

import httpx

from config import settings
from services.channels.base import (
    BaseChannelAdapter,
    IncomingMessage,
    OutgoingMessage,
    _DEFAULT_TIMEOUT,
    mime_to_extension,
)

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


class WhatsAppAdapter(BaseChannelAdapter):
    """WhatsApp Cloud API channel adapter."""

    channel_type = "whatsapp"

    # ── Webhook verification ──

    async def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        """Verify incoming webhook authenticity via HMAC-SHA256.

        Meta signs every webhook payload with the app secret.  The signature
        is delivered in the ``X-Hub-Signature-256`` header as
        ``sha256=<hex_digest>``.

        Args:
            payload: Raw request body bytes.
            headers: HTTP headers (keys should be lowercase).

        Returns:
            True if the signature is valid.
        """
        app_secret = settings.whatsapp_app_secret
        if not app_secret:
            logger.warning("whatsapp_app_secret not configured — skipping verification")
            return False

        signature_header = headers.get("x-hub-signature-256", "")
        if not signature_header.startswith("sha256="):
            logger.debug("Missing or malformed X-Hub-Signature-256 header")
            return False

        expected_sig = signature_header[len("sha256="):]
        computed_sig = hmac.new(
            app_secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed_sig, expected_sig)

    # ── Inbound message parsing ──

    async def parse_webhook(
        self, payload: dict, headers: dict
    ) -> IncomingMessage | None:
        """Parse a WhatsApp Cloud API webhook into an IncomingMessage.

        WhatsApp webhook structure::

            {
              "object": "whatsapp_business_account",
              "entry": [{
                "changes": [{
                  "value": {
                    "messages": [{
                      "from": "15551234567",
                      "id": "wamid.xxx",
                      "timestamp": "1700000000",
                      "type": "text",
                      "text": {"body": "Hello"}
                    }],
                    "metadata": {"phone_number_id": "..."}
                  }
                }]
              }]
            }

        Returns None for non-message events (status updates, read receipts, etc.).
        """
        try:
            entry = payload.get("entry", [])
            if not entry:
                return None

            changes = entry[0].get("changes", [])
            if not changes:
                return None

            value = changes[0].get("value", {})
            messages = value.get("messages")
            if not messages:
                # Status update, read receipt, or other non-message event
                return None

            msg = messages[0]
            msg_type = msg.get("type", "")
            sender = msg.get("from", "")
            message_id = msg.get("id", "")
            timestamp = float(msg.get("timestamp", 0))

            # Extract text content
            text = ""
            if msg_type == "text":
                text = msg.get("text", {}).get("body", "")
            elif msg_type == "image":
                text = msg.get("image", {}).get("caption", "")
            elif msg_type == "document":
                text = msg.get("document", {}).get("caption", "")

            # Extract media references
            media: list[dict] = []
            if msg_type == "image":
                image_data = msg.get("image", {})
                media.append({
                    "type": "image",
                    "media_id": image_data.get("id", ""),
                    "mime_type": image_data.get("mime_type", "image/jpeg"),
                    "sha256": image_data.get("sha256", ""),
                })
            elif msg_type == "audio":
                audio_data = msg.get("audio", {})
                media.append({
                    "type": "audio",
                    "media_id": audio_data.get("id", ""),
                    "mime_type": audio_data.get("mime_type", "audio/ogg"),
                })
            elif msg_type == "document":
                doc_data = msg.get("document", {})
                media.append({
                    "type": "document",
                    "media_id": doc_data.get("id", ""),
                    "mime_type": doc_data.get("mime_type", "application/octet-stream"),
                    "filename": doc_data.get("filename", ""),
                })

            # Only handle text and image types per spec; log others for debugging
            if msg_type not in ("text", "image"):
                logger.info(
                    "Unsupported WhatsApp message type '%s' from %s — ignoring",
                    msg_type,
                    sender,
                )
                return None

            return IncomingMessage(
                channel_type=self.channel_type,
                channel_id=sender,
                message_id=message_id,
                text=text,
                media=media,
                timestamp=timestamp,
                raw_payload=payload,
            )

        except (IndexError, KeyError, TypeError) as exc:
            logger.error("Failed to parse WhatsApp webhook: %s", exc, exc_info=True)
            return None

    # ── Outbound messaging ──

    async def send_message(self, message: OutgoingMessage) -> bool:
        """Send a text message via WhatsApp Cloud API.

        POST https://graph.facebook.com/v21.0/{phone_number_id}/messages

        The request body uses the standard WhatsApp Cloud API format with
        ``messaging_product: "whatsapp"``.

        Args:
            message: The outgoing message to send.

        Returns:
            True if the API responded with a 2xx status.
        """
        phone_number_id = settings.whatsapp_phone_number_id
        access_token = settings.whatsapp_access_token

        if not phone_number_id or not access_token:
            logger.error(
                "WhatsApp send_message failed: phone_number_id or access_token not configured"
            )
            return False

        url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": message.channel_id,
            "type": "text",
            "text": {"body": message.text},
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, json=body, headers=headers)

            if resp.status_code >= 400:
                logger.error(
                    "WhatsApp send_message failed: HTTP %d — %s",
                    resp.status_code,
                    resp.text,
                )
                return False

            logger.debug("WhatsApp message sent to %s", message.channel_id)
            return True

        except httpx.HTTPError as exc:
            logger.error("WhatsApp send_message HTTP error: %s", exc)
            return False

    # ── Media download ──

    async def download_media(
        self, media_url: str | None, media_id: str | None
    ) -> dict | None:
        """Download media from WhatsApp and return base64-encoded content.

        WhatsApp media download is a two-step process:
        1. GET ``/v21.0/{media_id}`` to obtain the actual download URL.
        2. GET the download URL (with Bearer auth) to fetch the binary data.

        Args:
            media_url: Not used for WhatsApp (URL must be fetched via media_id).
            media_id: WhatsApp media identifier from the webhook payload.

        Returns:
            Dict with ``data`` (base64), ``mime_type``, and ``filename`` keys,
            or None on failure.
        """
        if not media_id:
            logger.warning("download_media called without media_id")
            return None

        access_token = settings.whatsapp_access_token
        if not access_token:
            logger.error("WhatsApp download_media: access_token not configured")
            return None

        auth_headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                # Step 1: Get the media URL and metadata
                meta_url = f"{GRAPH_API_BASE}/{media_id}"
                meta_resp = await client.get(meta_url, headers=auth_headers)
                if meta_resp.status_code != 200:
                    logger.error(
                        "WhatsApp media metadata fetch failed: HTTP %d — %s",
                        meta_resp.status_code,
                        meta_resp.text,
                    )
                    return None

                meta = meta_resp.json()
                download_url = meta.get("url")
                # WhatsApp metadata provides the authoritative mime_type
                mime_type = meta.get("mime_type", "application/octet-stream")

                if not download_url:
                    logger.error("WhatsApp media metadata missing 'url' field")
                    return None

                # Step 2: Download the actual media binary
                media_resp = await client.get(download_url, headers=auth_headers)
                if media_resp.status_code != 200:
                    logger.error(
                        "WhatsApp media download failed: HTTP %d",
                        media_resp.status_code,
                    )
                    return None

                encoded = base64.b64encode(media_resp.content).decode("utf-8")

                ext = mime_to_extension(mime_type)
                filename = f"whatsapp_{media_id[:12]}{ext}"

                return {
                    "data": encoded,
                    "mime_type": mime_type,
                    "filename": filename,
                }

        except httpx.HTTPError as exc:
            logger.error("WhatsApp download_media HTTP error: %s", exc)
            return None

    # ── Typing indicator ──

    async def send_typing_indicator(self, channel_id: str) -> None:
        """Mark the conversation as read / show typing indicator.

        Sends a ``read`` action to the WhatsApp Cloud API which also
        triggers the typing indicator on the user's device.

        Args:
            channel_id: The recipient's phone number.
        """
        phone_number_id = settings.whatsapp_phone_number_id
        access_token = settings.whatsapp_access_token

        if not phone_number_id or not access_token:
            return

        url = f"{GRAPH_API_BASE}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        body = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": channel_id,  # WhatsApp uses message_id for read receipts
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # Typing indicators are best-effort; don't propagate failures
            logger.debug("WhatsApp typing indicator failed: %s", exc)
