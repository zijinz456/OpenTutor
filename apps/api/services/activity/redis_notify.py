"""Optional Redis pub/sub notification layer for the Activity Engine.

When ``activity_use_redis_notify`` is *True* and a Redis connection is
available, this module provides a lightweight pub/sub mechanism to wake the
engine loop immediately when a new task is submitted, instead of waiting for
the next polling interval.

If Redis is unavailable (not configured, connection refused, library missing,
etc.), every function in this module degrades to a silent no-op so that the
existing database-polling path continues to work without any changes.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Channel name used for task-ready notifications
# ---------------------------------------------------------------------------
TASK_READY_CHANNEL = "opentutor:task_ready"

# ---------------------------------------------------------------------------
# Lazy-initialized module-level Redis client
# ---------------------------------------------------------------------------
_redis_client: Any | None = None
_redis_available: bool | None = None  # None = not yet probed


async def _get_redis() -> Any | None:
    """Return a shared ``redis.asyncio.Redis`` instance, or *None* if Redis
    is unavailable.

    The first call probes the connection with a PING; subsequent calls return
    the cached result immediately.
    """
    global _redis_client, _redis_available

    if _redis_available is False:
        return None
    if _redis_client is not None:
        return _redis_client

    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("redis.asyncio not importable; Redis notify disabled")
        _redis_available = False
        return None

    from config import settings

    url = (settings.redis_url or "").strip()
    if not url:
        logger.debug("redis_url is empty; Redis notify disabled")
        _redis_available = False
        return None

    try:
        client = aioredis.from_url(url, decode_responses=True)
        await client.ping()
        _redis_client = client
        _redis_available = True
        logger.info("Redis notify: connected to %s", url)
        return client
    except (OSError, ConnectionError, TimeoutError, RuntimeError) as exc:
        logger.warning("Redis notify: connection failed; falling back to polling (%s)", type(exc).__name__, exc_info=True)
        _redis_available = False
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def notify_task_ready(task_id: str) -> None:
    """Publish a notification that a task is ready for execution.

    This is a fire-and-forget call.  If Redis is not available or the publish
    fails, the error is logged at *debug* level and silently swallowed so that
    the caller (``submit_task``) is never affected.
    """
    try:
        client = await _get_redis()
        if client is None:
            return
        await client.publish(TASK_READY_CHANNEL, str(task_id))
        logger.debug("Redis notify: published task_ready for %s", task_id)
    except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
        logger.exception("Redis notify: publish failed: %s", exc)


async def wait_for_task_notification(timeout: float = 5.0) -> str | None:
    """Subscribe to the ``task_ready`` channel and wait up to *timeout* seconds
    for a notification.

    Returns the ``task_id`` string from the first message received, or *None*
    if the timeout expires or Redis is not available.

    Each call creates a fresh subscription so that the engine loop does not
    need to manage long-lived subscriber state.  The overhead is negligible
    compared to the typical task execution time.
    """
    try:
        client = await _get_redis()
        if client is None:
            return None

        pubsub = client.pubsub()
        await pubsub.subscribe(TASK_READY_CHANNEL)
        try:
            # get_message returns None when no message is available.
            # We poll in short increments up to *timeout*.
            elapsed = 0.0
            step = min(0.25, timeout)
            while elapsed < timeout:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=step)
                if msg is not None and msg.get("type") == "message":
                    data = msg.get("data")
                    logger.debug("Redis notify: received task_ready for %s", data)
                    return str(data) if data else None
                elapsed += step
        finally:
            await pubsub.unsubscribe(TASK_READY_CHANNEL)
            await pubsub.aclose()
    except (ConnectionError, TimeoutError, OSError, RuntimeError) as exc:
        logger.exception("Redis notify: wait failed: %s", exc)
    return None


async def close_redis() -> None:
    """Gracefully close the shared Redis connection (called on shutdown)."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except (ConnectionError, TimeoutError, OSError, RuntimeError):
            logger.debug("Redis close error", exc_info=True)
    _redis_client = None
    _redis_available = None
