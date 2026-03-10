"""Agenda signal collectors package.

Each collector queries one data source and returns zero or more AgendaSignal
instances.  The agenda service calls ``collect_signals`` which fans out to
all collectors and returns a flat list.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

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


async def collect_signals(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> list[AgendaSignal]:
    """Run all signal collectors concurrently and return a flat list of signals."""
    if db is None:
        raise ValueError("db session is required")

    async def _safe_collect(collector) -> list[AgendaSignal]:
        try:
            return await collector(user_id, course_id, db)
        except (SQLAlchemyError, ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as exc:
            logger.exception("Signal collector %s failed: %s", collector.__name__, exc)
            return []

    results = await asyncio.gather(*[_safe_collect(c) for c in _COLLECTORS])
    return [signal for batch in results for signal in batch]


__all__ = [
    "AgendaSignal",
    "SIGNAL_TYPES",
    "collect_signals",
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
