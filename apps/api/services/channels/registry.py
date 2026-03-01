"""Channel adapter registry — factory for messaging platform adapters.

Lazily instantiates and caches adapter instances. Determines which channels
are active based on whether the required credentials are configured.
"""

import logging

from config import settings
from services.channels.base import BaseChannelAdapter

logger = logging.getLogger(__name__)

# Singleton cache of adapter instances
_adapters: dict[str, BaseChannelAdapter] = {}


def _is_channel_configured(channel_type: str) -> bool:
    """Check if the required credentials for a channel are present in settings."""
    checks = {
        "whatsapp": lambda: bool(
            settings.whatsapp_phone_number_id and settings.whatsapp_access_token
        ),
        "imessage": lambda: bool(
            settings.bluebubbles_server_url and settings.bluebubbles_password
        ),
    }
    check = checks.get(channel_type)
    return check() if check else False


def get_adapter(channel_type: str) -> BaseChannelAdapter:
    """Get (or lazily create) an adapter instance for the given channel type.

    Raises ValueError if the channel type is unknown or not configured.
    """
    if channel_type in _adapters:
        return _adapters[channel_type]

    if not _is_channel_configured(channel_type):
        raise ValueError(
            f"Channel '{channel_type}' is not configured. "
            f"Check your .env for the required credentials."
        )

    adapter = _create_adapter(channel_type)
    _adapters[channel_type] = adapter
    logger.info("Initialized %s channel adapter", channel_type)
    return adapter


def _create_adapter(channel_type: str) -> BaseChannelAdapter:
    """Instantiate the adapter class for a given channel type.

    Imports are deferred to avoid loading platform SDKs unless needed.
    """
    if channel_type == "whatsapp":
        from services.channels.whatsapp import WhatsAppAdapter
        return WhatsAppAdapter()

    if channel_type == "imessage":
        from services.channels.imessage import IMessageAdapter
        return IMessageAdapter()

    raise ValueError(f"Unknown channel type: '{channel_type}'")


def get_all_adapters() -> list[BaseChannelAdapter]:
    """Return adapter instances for all configured (active) channels.

    Only returns adapters for channels whose credentials are present.
    Does not raise on misconfigured channels — just skips them.
    """
    known_channels = ["whatsapp", "imessage"]
    active = []

    for channel_type in known_channels:
        if _is_channel_configured(channel_type):
            try:
                adapter = get_adapter(channel_type)
                active.append(adapter)
            except Exception as exc:
                logger.warning(
                    "Failed to initialize %s adapter: %s", channel_type, exc
                )

    return active
