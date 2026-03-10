"""Block preference computation from user interaction events.

Uses PreferenceSignal model to store block engagement events and computes
weighted preference scores with exponential decay.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Scoring weights for different event types
EVENT_WEIGHTS: dict[str, float] = {
    "approve": 1.0,
    "dismiss": -1.5,
    "manual_add": 2.0,
    "manual_remove": -2.0,
    "view": 0.1,  # Per 30s of viewing
}

DECAY_HALF_LIFE_DAYS = 14.0


async def record_block_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    event_type: str,
    block_type: str,
    metadata: dict | None = None,
) -> None:
    """Record a block interaction event as a PreferenceSignal."""
    try:
        from models.preference import PreferenceSignal

        signal = PreferenceSignal(
            user_id=user_id,
            course_id=course_id,
            signal_type="behavior",
            dimension=f"block_{event_type}",
            value=block_type,
            context=metadata or {},
        )
        db.add(signal)
        await db.flush()
    except Exception as e:
        logger.debug("Failed to record block event: %s", e)


async def compute_block_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict[str, dict]:
    """Compute per-block-type preference scores with exponential time decay.

    Returns a dict mapping block_type -> {"score": float, "dismiss_count": int}.
    """
    try:
        from models.preference import PreferenceSignal

        result = await db.execute(
            select(PreferenceSignal).where(
                PreferenceSignal.user_id == user_id,
                PreferenceSignal.course_id == course_id,
                PreferenceSignal.signal_type == "behavior",
                PreferenceSignal.dimension.like("block_%"),
            )
        )
        signals = result.scalars().all()
    except Exception as e:
        logger.debug("Failed to query block preferences: %s", e)
        return {}

    now = datetime.now(timezone.utc)
    scores: dict[str, float] = {}
    dismiss_counts: dict[str, int] = {}

    for sig in signals:
        event_type = sig.dimension.removeprefix("block_")
        block_type = sig.value

        # Track raw dismiss count (un-decayed)
        if event_type == "dismiss":
            dismiss_counts[block_type] = dismiss_counts.get(block_type, 0) + 1

        weight = EVENT_WEIGHTS.get(event_type, 0.0)
        if weight == 0.0:
            continue

        # Apply time decay
        age_days = (now - sig.created_at).total_seconds() / 86400
        decay = math.exp(-0.693 * age_days / DECAY_HALF_LIFE_DAYS)

        # For view events, scale by duration
        if event_type == "view" and isinstance(sig.context, dict):
            duration_ms = sig.context.get("duration_ms", 0)
            # 0.1 points per 30s of viewing
            weight = weight * (duration_ms / 30_000)

        scores[block_type] = scores.get(block_type, 0.0) + weight * decay

    # Merge into unified result
    all_types = set(scores) | set(dismiss_counts)
    return {
        bt: {
            "score": round(scores.get(bt, 0.0), 3),
            "dismiss_count": dismiss_counts.get(bt, 0),
        }
        for bt in all_types
    }
