"""Block preference computation from user interaction events.

Uses PreferenceSignal model to store block engagement events and computes
weighted preference scores with exponential decay. Also incorporates
onboarding interview preferences (UserPreference) as initial score boosts.
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
    "view": 0.1,            # Per 30s of viewing
    "effective_review": 1.5, # Review block led to improved quiz accuracy
    "study_time": 0.2,      # Per 60s of focused interaction time
}

DECAY_HALF_LIFE_DAYS = 14.0

# Bounds to prevent extreme preference scores
SCORE_FLOOR = -10.0    # Minimum total preference score per block type
SCORE_CEILING = 20.0   # Maximum total preference score per block type
VIEW_WEIGHT_CAP = 2.0  # Max weight multiplier for duration-scaled events

# Query limit to prevent full table scans on heavy users
SIGNAL_QUERY_LIMIT = 500


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
        logger.warning("Failed to record block event: %s", e)


# Onboarding preference dimension -> block types they boost
_ONBOARDING_BLOCK_MAP: dict[str, list[str]] = {
    "prefers_note_taking":      ["notes"],
    "prefers_visual_aids":      ["knowledge_graph"],
    "prefers_active_recall":    ["quiz", "flashcards"],
    "prefers_mistake_analysis": ["wrong_answers"],
    "prefers_spaced_review":    ["review", "forecast"],
    "prefers_planning":         ["plan"],
}

# Score boost for onboarding-sourced preferences (applied once as a baseline)
ONBOARDING_BOOST = 3.0


async def _load_onboarding_boosts(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, float]:
    """Load onboarding interview preferences and convert to block score boosts."""
    try:
        from models.preference import UserPreference

        result = await db.execute(
            select(UserPreference).where(
                UserPreference.user_id == user_id,
                UserPreference.source == "onboarding_interview",
            )
        )
        prefs = result.scalars().all()
    except Exception as e:
        logger.warning("Failed to load onboarding preferences: %s", e)
        return {}

    boosts: dict[str, float] = {}
    for pref in prefs:
        block_types = _ONBOARDING_BLOCK_MAP.get(pref.dimension)
        if block_types and pref.value == "true":
            confidence = getattr(pref, "confidence", 0.7) or 0.7
            for bt in block_types:
                boosts[bt] = boosts.get(bt, 0.0) + ONBOARDING_BOOST * confidence
    return boosts


async def compute_block_preferences(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict[str, dict]:
    """Compute per-block-type preference scores with exponential time decay.

    Incorporates onboarding interview preferences as initial score boosts,
    then layers behavioral signal scores on top.

    Returns a dict mapping block_type -> {"score": float, "dismiss_count": int}.
    """
    # Start with onboarding boosts (global, not course-specific)
    onboarding_boosts = await _load_onboarding_boosts(db, user_id)

    try:
        from models.preference import PreferenceSignal

        result = await db.execute(
            select(PreferenceSignal).where(
                PreferenceSignal.user_id == user_id,
                PreferenceSignal.course_id == course_id,
                PreferenceSignal.signal_type == "behavior",
                PreferenceSignal.dimension.like("block_%"),
            )
            .order_by(PreferenceSignal.created_at.desc())
            .limit(SIGNAL_QUERY_LIMIT)
        )
        signals = result.scalars().all()
    except Exception as e:
        logger.warning("Failed to query block preferences: %s", e)
        signals = []

    now = datetime.now(timezone.utc)
    scores: dict[str, float] = dict(onboarding_boosts)
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

        # For view events, scale by duration (capped to prevent outliers)
        if event_type == "view" and isinstance(sig.context, dict):
            duration_ms = sig.context.get("duration_ms", 0)
            weight = min(weight * (duration_ms / 30_000), VIEW_WEIGHT_CAP)

        # For study_time events, scale by focused interaction duration (capped)
        if event_type == "study_time" and isinstance(sig.context, dict):
            duration_ms = sig.context.get("duration_ms", 0)
            weight = min(weight * (duration_ms / 60_000), VIEW_WEIGHT_CAP)

        scores[block_type] = max(SCORE_FLOOR, min(SCORE_CEILING,
            scores.get(block_type, 0.0) + weight * decay))

    # Merge into unified result
    all_types = set(scores) | set(dismiss_counts)
    return {
        bt: {
            "score": round(scores.get(bt, 0.0), 3),
            "dismiss_count": dismiss_counts.get(bt, 0),
        }
        for bt in all_types
    }
