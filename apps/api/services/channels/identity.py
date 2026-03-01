"""Channel identity resolution — maps external messaging IDs to User records.

Handles two flows:
1. resolve_or_create_user: auto-provision a User + ChannelBinding for first-time
   channel users (zero-friction onboarding).
2. bind_existing_user: link an existing User account to a new channel (account linking).
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from models.channel_binding import ChannelBinding

logger = logging.getLogger(__name__)


async def resolve_or_create_user(
    db: AsyncSession,
    channel_type: str,
    channel_id: str,
) -> tuple[User, ChannelBinding]:
    """Look up (or auto-create) a User and ChannelBinding for a channel identity.

    Flow:
    1. Query ChannelBinding by (channel_type, channel_id).
    2. If found, load and return the associated User.
    3. If not found, create a new User (named after the channel) and ChannelBinding.

    Returns:
        (user, binding) tuple — always non-None.
    """
    # 1. Look up existing binding
    stmt = select(ChannelBinding).where(
        ChannelBinding.channel_type == channel_type,
        ChannelBinding.channel_id == channel_id,
    )
    result = await db.execute(stmt)
    binding = result.scalar_one_or_none()

    if binding is not None:
        # Load the associated user
        user_stmt = select(User).where(User.id == binding.user_id)
        user_result = await db.execute(user_stmt)
        user = user_result.scalar_one_or_none()

        if user is None:
            # Orphaned binding — user was deleted; recreate
            logger.warning(
                "Orphaned ChannelBinding %s for %s:%s — recreating user",
                binding.id, channel_type, channel_id,
            )
            user = User(
                name=f"{channel_type.title()} User",
            )
            db.add(user)
            await db.flush()
            binding.user_id = user.id
            await db.flush()

        return user, binding

    # 2. No binding found — create new User + ChannelBinding
    display_name = _derive_display_name(channel_type, channel_id)

    user = User(
        name=display_name,
    )
    db.add(user)
    await db.flush()

    binding = ChannelBinding(
        user_id=user.id,
        channel_type=channel_type,
        channel_id=channel_id,
        display_name=display_name,
        is_verified=False,
    )
    db.add(binding)
    await db.flush()

    logger.info(
        "Auto-created user %s with %s binding for %s",
        user.id, channel_type, channel_id,
    )
    return user, binding


async def bind_existing_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    channel_type: str,
    channel_id: str,
) -> ChannelBinding:
    """Link an existing User account to a new channel identity.

    Used when a user wants to connect their web account to WhatsApp/iMessage.
    If a binding already exists for this (channel_type, channel_id), it is
    re-pointed to the given user_id.

    Returns:
        The created or updated ChannelBinding.
    """
    # Check for existing binding with this channel identity
    stmt = select(ChannelBinding).where(
        ChannelBinding.channel_type == channel_type,
        ChannelBinding.channel_id == channel_id,
    )
    result = await db.execute(stmt)
    binding = result.scalar_one_or_none()

    if binding is not None:
        if binding.user_id == user_id:
            # Already bound to this user — no-op
            return binding

        # Re-bind to the new user (account merge / takeover)
        logger.info(
            "Re-binding %s:%s from user %s to user %s",
            channel_type, channel_id, binding.user_id, user_id,
        )
        binding.user_id = user_id
        binding.is_verified = True
        await db.flush()
        return binding

    # Create new binding
    binding = ChannelBinding(
        user_id=user_id,
        channel_type=channel_type,
        channel_id=channel_id,
        display_name=_derive_display_name(channel_type, channel_id),
        is_verified=True,  # Explicitly linked by authenticated user
    )
    db.add(binding)
    await db.flush()

    logger.info(
        "Bound user %s to %s channel %s",
        user_id, channel_type, channel_id,
    )
    return binding


def _derive_display_name(channel_type: str, channel_id: str) -> str:
    """Generate a human-readable display name from channel identity.

    Masks phone numbers for privacy, keeps email handles readable.
    """
    if channel_type == "whatsapp" and channel_id.startswith("+"):
        # Mask middle digits: +1234567890 → +1***7890
        if len(channel_id) > 6:
            return f"{channel_id[:2]}***{channel_id[-4:]}"
        return channel_id
    if channel_type == "imessage" and "@" in channel_id:
        # Keep first 3 chars of local part: user@example.com → use***@example.com
        local, domain = channel_id.split("@", 1)
        masked_local = local[:3] + "***" if len(local) > 3 else local
        return f"{masked_local}@{domain}"
    return f"{channel_type.title()} User"
