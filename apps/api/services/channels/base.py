"""Base channel adapter — abstract interface for messaging platform integrations.

Each messaging platform (WhatsApp, iMessage, etc.) implements this ABC.
Provides a uniform interface for webhook parsing, message sending, and media handling.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    """Normalized representation of an inbound message from any channel."""

    channel_type: str
    channel_id: str
    message_id: str
    text: str
    media: list[dict] = field(default_factory=list)
    # e.g. [{"type": "image", "url": "...", "media_id": "...", "mime_type": "image/jpeg"}]
    timestamp: float = 0.0
    raw_payload: dict = field(default_factory=dict)
    is_group: bool = False
    group_id: Optional[str] = None


@dataclass
class OutgoingMessage:
    """Normalized representation of an outbound message to any channel."""

    channel_id: str
    text: str
    media: list[dict] = field(default_factory=list)
    # e.g. [{"type": "image", "url": "...", "caption": "..."}]
    reply_to_message_id: Optional[str] = None


class BaseChannelAdapter(ABC):
    """Abstract base for messaging platform adapters.

    Subclasses must implement the abstract methods for their specific platform API.
    Concrete helper methods (send_error, send_typing_indicator) provide shared behavior.
    """

    channel_type: str = ""

    @abstractmethod
    async def verify_webhook(self, payload: bytes, headers: dict) -> bool:
        """Verify webhook signature / authenticity for this platform.

        Args:
            payload: Raw request body bytes.
            headers: HTTP headers from the request (lowercase keys).

        Returns:
            True if the request is verified, False otherwise.
        """
        ...

    @abstractmethod
    async def parse_webhook(
        self, payload: dict, headers: dict
    ) -> IncomingMessage | None:
        """Parse an incoming webhook payload into an IncomingMessage.

        Returns None if the webhook is not a user message (e.g. delivery receipt,
        status update, or echo).

        Args:
            payload: Parsed JSON body of the webhook request.
            headers: HTTP headers from the request.
        """
        ...

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> bool:
        """Send an outgoing message via the platform API.

        Returns True if the message was sent successfully, False otherwise.
        """
        ...

    @abstractmethod
    async def download_media(
        self, media_url: str | None, media_id: str | None
    ) -> dict | None:
        """Download and base64-encode media from the channel.

        Args:
            media_url: Direct URL to the media (if available).
            media_id: Provider-specific media identifier (if available).

        Returns:
            A dict with keys ``data`` (base64 str), ``mime_type``, and
            ``filename``, or None on failure.
        """
        ...

    async def send_typing_indicator(self, channel_id: str) -> None:
        """Send a typing/composing indicator if the platform supports it.

        Default implementation is a no-op. Override in platform adapters that
        support typing indicators (e.g. WhatsApp).
        """
        pass

    # ── Concrete helpers ──

    async def send_error(self, channel_id: str, error_text: str | None = None) -> None:
        """Send a user-friendly error message to the channel.

        Swallows exceptions to prevent error-sending failures from masking
        the original error.
        """
        text = error_text or (
            "Sorry, something went wrong processing your message. "
            "Please try again in a moment."
        )
        try:
            await self.send_message(OutgoingMessage(channel_id=channel_id, text=text))
        except Exception as exc:
            logger.error("Failed to send error message to %s: %s", channel_id, exc)
