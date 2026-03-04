"""Discord bot adapter for multi-channel messaging.

Implements BaseChannelAdapter for Discord's Interaction-based webhook model.
Supports slash commands (``/ask``) and DM-based interactions via Discord's
HTTP interactions endpoint (no gateway connection required).

Discord verifies webhook authenticity using Ed25519 signatures, which are
checked in ``verify_webhook``.

Docs: https://discord.com/developers/docs/interactions/receiving-and-responding
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
)

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"

# Discord interaction types
INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
INTERACTION_MESSAGE_COMPONENT = 3

# Discord interaction response types
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE = 4
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5


class DiscordAdapter(BaseChannelAdapter):
    """Discord interactions-based channel adapter."""

    channel_type = "discord"

    # ── Webhook verification ──

    async def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        """Verify incoming Discord interaction via Ed25519 signature.

        Discord requires webhook endpoints to validate the ``X-Signature-Ed25519``
        and ``X-Signature-Timestamp`` headers against the application's public key.

        If the ``discord_public_key`` setting is not configured, verification is
        skipped with a warning (useful for development but not production).

        Args:
            payload: Raw request body bytes.
            headers: HTTP headers (keys should be lowercase).

        Returns:
            True if the signature is valid or public key is not configured.
        """
        public_key = settings.discord_public_key
        if not public_key:
            logger.warning(
                "discord_public_key not configured — skipping signature verification"
            )
            # In development, allow unverified requests; in production the
            # public key should always be set.
            return bool(settings.discord_bot_token)

        signature = headers.get("x-signature-ed25519", "")
        timestamp = headers.get("x-signature-timestamp", "")

        if not signature or not timestamp:
            logger.debug("Missing Discord signature headers")
            return False

        try:
            from nacl.signing import VerifyKey
            from nacl.exceptions import BadSignatureError

            verify_key = VerifyKey(bytes.fromhex(public_key))
            verify_key.verify(
                timestamp.encode("utf-8") + payload,
                bytes.fromhex(signature),
            )
            return True
        except ImportError:
            logger.warning(
                "PyNaCl not installed — cannot verify Discord signatures. "
                "Install with: pip install PyNaCl"
            )
            # Fall back to allowing the request if bot token is configured
            return bool(settings.discord_bot_token)
        except BadSignatureError:
            logger.warning("Discord webhook signature verification failed")
            return False
        except Exception as exc:
            logger.error("Discord signature verification error: %s", exc)
            return False

    # ── Inbound message parsing ──

    async def parse_webhook(
        self, payload: dict, headers: dict
    ) -> IncomingMessage | None:
        """Parse a Discord Interaction into an IncomingMessage.

        Discord interaction payload structure for slash commands::

            {
              "type": 2,  // APPLICATION_COMMAND
              "data": {
                "name": "ask",
                "options": [
                  {"name": "question", "value": "What is photosynthesis?"}
                ]
              },
              "member": {"user": {"id": "123", "username": "alice"}},
              "channel_id": "456",
              "id": "789",
              "token": "interaction-token"
            }

        Returns None for PING interactions (handled separately in the webhook
        endpoint) and unsupported interaction types.
        """
        try:
            interaction_type = payload.get("type", 0)

            # PING — handled at the router level, not here
            if interaction_type == INTERACTION_PING:
                return None

            # APPLICATION_COMMAND — slash commands
            if interaction_type == INTERACTION_APPLICATION_COMMAND:
                return self._parse_slash_command(payload)

            logger.debug(
                "Unsupported Discord interaction type: %d", interaction_type
            )
            return None

        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.error(
                "Failed to parse Discord interaction: %s", exc, exc_info=True
            )
            return None

    def _parse_slash_command(self, payload: dict) -> IncomingMessage | None:
        """Parse a slash command interaction into an IncomingMessage."""
        data = payload.get("data", {})
        command_name = data.get("name", "")

        # Extract user info — could be in member.user (guild) or user (DM)
        user_info = (
            payload.get("member", {}).get("user", {})
            or payload.get("user", {})
        )
        user_id = user_info.get("id", "")
        channel_id = payload.get("channel_id", "")
        interaction_id = payload.get("id", "")

        if not user_id:
            return None

        # Build text from command + options
        if command_name == "ask":
            options = data.get("options", [])
            question = next(
                (o["value"] for o in options if o["name"] == "question"),
                "",
            )
            text = question
        elif command_name == "study":
            options = data.get("options", [])
            topic = next(
                (o["value"] for o in options if o["name"] == "topic"),
                "",
            )
            text = f"/study {topic}" if topic else "/study"
        elif command_name == "quiz":
            text = "/quiz"
        elif command_name == "help":
            text = "/help"
        else:
            # Generic: just pass the command name as text
            options = data.get("options", [])
            option_texts = [
                f"{o['name']}={o['value']}" for o in options if "value" in o
            ]
            text = f"/{command_name} {' '.join(option_texts)}".strip()

        if not text:
            return None

        # Store the interaction token in raw_payload for deferred responses
        return IncomingMessage(
            channel_type=self.channel_type,
            channel_id=user_id,  # Use Discord user ID as channel_id
            message_id=interaction_id,
            text=text,
            timestamp=0.0,  # Discord interactions don't include a timestamp
            raw_payload=payload,
            is_group=bool(payload.get("guild_id")),
            group_id=payload.get("guild_id"),
        )

    # ── Outbound messaging ──

    async def send_message(self, message: OutgoingMessage) -> bool:
        """Send a message via Discord Bot API (create DM channel, then send).

        For new conversations, this creates a DM channel with the user first,
        then sends the message to that channel.

        Args:
            message: The outgoing message to send.

        Returns:
            True if the message was sent successfully.
        """
        bot_token = settings.discord_bot_token
        if not bot_token:
            logger.error("Discord send_message failed: discord_bot_token not configured")
            return False

        auth_headers = {
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                # Step 1: Create/get DM channel with the user
                dm_resp = await client.post(
                    f"{DISCORD_API_BASE}/users/@me/channels",
                    json={"recipient_id": message.channel_id},
                    headers=auth_headers,
                )

                if dm_resp.status_code >= 400:
                    logger.error(
                        "Discord create DM failed: HTTP %d — %s",
                        dm_resp.status_code,
                        dm_resp.text,
                    )
                    return False

                dm_channel_id = dm_resp.json().get("id")
                if not dm_channel_id:
                    logger.error("Discord create DM response missing channel ID")
                    return False

                # Step 2: Send message to the DM channel
                # Truncate if over Discord's 2000-char limit
                text = message.text
                if len(text) > 2000:
                    text = text[:1997] + "..."

                msg_resp = await client.post(
                    f"{DISCORD_API_BASE}/channels/{dm_channel_id}/messages",
                    json={"content": text},
                    headers=auth_headers,
                )

                if msg_resp.status_code >= 400:
                    logger.error(
                        "Discord send_message failed: HTTP %d — %s",
                        msg_resp.status_code,
                        msg_resp.text,
                    )
                    return False

            logger.debug("Discord message sent to user %s", message.channel_id)
            return True

        except httpx.HTTPError as exc:
            logger.error("Discord send_message HTTP error: %s", exc)
            return False

    # ── Interaction responses ──

    async def send_interaction_response(
        self,
        interaction_id: str,
        interaction_token: str,
        content: str,
        response_type: int = RESPONSE_CHANNEL_MESSAGE,
    ) -> bool:
        """Send a response to a Discord interaction (slash command reply).

        This is the primary way to respond to slash commands. The response
        appears in the channel where the command was invoked.

        Args:
            interaction_id: The interaction's unique ID.
            interaction_token: The interaction's token (for authentication).
            content: The response text content.
            response_type: Discord response type (default: CHANNEL_MESSAGE).

        Returns:
            True if the response was sent successfully.
        """
        url = f"{DISCORD_API_BASE}/interactions/{interaction_id}/{interaction_token}/callback"

        # Truncate if over Discord's 2000-char limit
        if len(content) > 2000:
            content = content[:1997] + "..."

        body = {
            "type": response_type,
            "data": {"content": content},
        }

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, json=body)

            if resp.status_code >= 400:
                logger.error(
                    "Discord interaction response failed: HTTP %d — %s",
                    resp.status_code,
                    resp.text,
                )
                return False

            return True

        except httpx.HTTPError as exc:
            logger.error("Discord interaction response HTTP error: %s", exc)
            return False

    # ── Media download ──

    async def download_media(
        self, media_url: str | None, media_id: str | None
    ) -> dict | None:
        """Download media from Discord CDN and return base64-encoded content.

        Discord attachments include direct CDN URLs in the webhook payload,
        so we download directly from the provided URL.

        Args:
            media_url: Direct URL to the Discord CDN resource.
            media_id: Not used for Discord (URL is sufficient).

        Returns:
            Dict with ``data`` (base64), ``mime_type``, and ``filename`` keys,
            or None on failure.
        """
        if not media_url:
            logger.warning("Discord download_media called without media_url")
            return None

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(media_url)

            if resp.status_code != 200:
                logger.error(
                    "Discord media download failed: HTTP %d", resp.status_code
                )
                return None

            filename = media_url.rsplit("/", 1)[-1].split("?")[0]
            return encode_media_response(resp, filename=filename)

        except httpx.HTTPError as exc:
            logger.error("Discord download_media HTTP error: %s", exc)
            return None

    # ── Typing indicator ──

    async def send_typing_indicator(self, channel_id: str) -> None:
        """Send a typing indicator in a Discord channel.

        For DM-based interactions this requires knowing the DM channel ID,
        which we may not have at this point. This is a best-effort no-op
        for the interaction-based flow.
        """
        # Discord typing indicators require a channel ID, not a user ID.
        # In the interaction flow we respond directly to the interaction,
        # so typing indicators are not applicable.
        pass
