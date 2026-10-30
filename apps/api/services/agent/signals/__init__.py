"""Agenda signal collectors package.

Each collector queries one data source and returns zero or more AgendaSignal
instances.  The agenda service calls ``collect_signals`` which fans out to
all collectors and returns a flat list.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ._types import AgendaSignal, SIGNAL_TYPES
from .study_signals import (
    _collect_active_goals,
    _collect_deadlines,
    _collect_forgetting_risk,
    _collect_lector_review,
    _collect_prerequisite_gaps,
)
from .review_signals import (
    _collect_weak_areas,
    _collect_content_stale,
    _collect_layout_adaptation,
)
from .activity_signals import (
    _collect_failed_tasks,
    _collect_inactivity,
    _collect_guided_session_readiness,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_COLLECTORS = [
    _collect_active_goals,
    _collect_deadlines,
    _collect_failed_tasks,
    _collect_forgetting_risk,
    _collect_lector_review,
    _collect_prerequisite_gaps,
    _collect_weak_areas,
    _collect_content_stale,
    _collect_inactivity,
    _collect_guided_session_readiness,
    _collect_layout_adaptation,
]


# Per-chat-session cache: signals only feed block-decision badges, so a
# 60s-stale result is fine and saves ~12 queries per turn.  Bounded LRU.
SIGNAL_CACHE_TTL_SECONDS = 60.0
SIGNAL_CACHE_MAX_ENTRIES = 500
_signal_cache: "OrderedDict[str, tuple[float, list[AgendaSignal]]]" = OrderedDict()


def clear_signal_cache() -> None:
    _signal_cache.clear()


def _cache_get(key: str, now: float) -> list[AgendaSignal] | None:
    entry = _signal_cache.get(key)
    if entry is None:
        return None
    stored_at, signals = entry
    if now - stored_at > SIGNAL_CACHE_TTL_SECONDS:
        _signal_cache.pop(key, None)
        return None
    _signal_cache.move_to_end(key)
    return list(signals)


def _cache_put(key: str, now: float, signals: list[AgendaSignal]) -> None:
    _signal_cache[key] = (now, list(signals))
    _signal_cache.move_to_end(key)
    while len(_signal_cache) > SIGNAL_CACHE_MAX_ENTRIES:
        _signal_cache.popitem(last=False)


async def collect_signals(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
    *,
    cache_key: str | None = None,
) -> list[AgendaSignal]:
    """Run all signal collectors and return a flat list of signals.

    Collectors run sequentially: they share one AsyncSession, and SQLAlchemy
    sessions are not safe for concurrent ``asyncio.gather`` use.  Pass
    ``cache_key`` (e.g. the chat session id) to reuse a result for
    ``SIGNAL_CACHE_TTL_SECONDS``; the agenda tick passes none so it always
    sees fresh data.
    """
    if db is None:
        raise ValueError("db session is required")

    now = time.monotonic()
    if cache_key is not None:
        cached = _cache_get(cache_key, now)
        if cached is not None:
            return cached

    signals: list[AgendaSignal] = []
    for collector in _COLLECTORS:
        try:
            signals.extend(await collector(user_id, course_id, db))
        except (SQLAlchemyError, ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as exc:
            logger.exception("Signal collector %s failed: %s", collector.__name__, exc)

    if cache_key is not None:
        _cache_put(cache_key, now, signals)
    return signals


__all__ = [
    "AgendaSignal",
    "SIGNAL_TYPES",
    "collect_signals",
    "clear_signal_cache",
    # Individual collectors (exposed for testing)
    "_collect_active_goals",
    "_collect_deadlines",
    "_collect_failed_tasks",
    "_collect_forgetting_risk",
    "_collect_lector_review",
    "_collect_prerequisite_gaps",
    "_collect_weak_areas",
    "_collect_content_stale",
    "_collect_inactivity",
    "_collect_guided_session_readiness",
    "_collect_layout_adaptation",
]
