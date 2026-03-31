"""Preference confidence calculator with 90-day decay.

Formula: confidence = base_score × frequency_factor × recency_factor × consistency_factor

- base_score: explicit=0.7, modification=0.5, behavior=0.3, negative=0.6
- frequency_factor: min(signal_count / 5, 1.0) — 5 signals = max frequency
- recency_factor: exp(-days / 90) — exponential decay over 90 days
- consistency_factor: agreement_ratio among signals for same dimension

Phase 0-C: Simple version. Phase 1: adds session weight and context diversity.
"""

import math
import uuid
from datetime import datetime, timezone
from collections import Counter

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.preference import PreferenceSignal, UserPreference

# Base scores by signal type
BASE_SCORES = {
    "explicit": 0.7,
    "modification": 0.5,
    "behavior": 0.3,
    "negative": 0.6,
}

# Confidence threshold to promote signal → preference
PROMOTION_THRESHOLD = 0.4


def recency_factor(signal_date: datetime) -> float:
    """Exponential decay: exp(-days/90). Recent signals weigh more."""
    now = datetime.now(timezone.utc)
    # Normalize naive datetimes to UTC before arithmetic
    if signal_date.tzinfo is None:
        signal_date = signal_date.replace(tzinfo=timezone.utc)
    days = (now - signal_date).total_seconds() / 86400
    return math.exp(-days / 90)


async def calculate_confidence(
    db: AsyncSession,
    user_id: uuid.UUID,
    dimension: str,
    course_id: uuid.UUID | None = None,
) -> tuple[float, str | None]:
    """Calculate confidence for a preference dimension based on accumulated signals.

    Returns (confidence_score, most_likely_value).
    """
    # Fetch all signals for this dimension
    query = (
        select(PreferenceSignal)
        .where(
            PreferenceSignal.user_id == user_id,
            PreferenceSignal.dimension == dimension,
            PreferenceSignal.dismissed_at.is_(None),
        )
        .order_by(PreferenceSignal.created_at.desc())
    )
    if course_id:
        query = query.where(PreferenceSignal.course_id == course_id)

    result = await db.execute(query)
    signals = result.scalars().all()

    if not signals:
        return 0.0, None

    # Calculate weighted scores per value
    value_scores: dict[str, float] = {}
    value_counts: Counter[str] = Counter()

    for signal in signals:
        base = BASE_SCORES.get(signal.signal_type, 0.3)
        recency = recency_factor(signal.created_at)
        score = base * recency
        value_scores[signal.value] = value_scores.get(signal.value, 0) + score
        value_counts[signal.value] += 1

    # Most likely value = highest weighted score
    best_value = max(value_scores, key=value_scores.get)

    # Frequency factor: min(count / 5, 1.0)
    total_signals = len(signals)
    frequency = min(total_signals / 5, 1.0)

    # Consistency factor: what % of signals agree on the best value
    consistency = value_counts[best_value] / total_signals

    # Best base score (use the most "authoritative" signal type)
    best_base = max(
        BASE_SCORES.get(s.signal_type, 0.3) for s in signals if s.value == best_value
    )

    # Best recency (most recent matching signal)
    best_recency = max(
        recency_factor(s.created_at) for s in signals if s.value == best_value
    )

    confidence = best_base * frequency * best_recency * consistency
    return min(confidence, 1.0), best_value


async def process_signal_to_preference(
    db: AsyncSession,
    user_id: uuid.UUID,
    dimension: str,
    course_id: uuid.UUID | None = None,
) -> UserPreference | None:
    """Check if signals for a dimension have enough confidence to become a preference.

    Called after a new signal is recorded. If confidence >= threshold,
    upserts the corresponding UserPreference entry.

    Fast-path: a single explicit signal immediately clears the threshold
    (confidence forced to >= 0.5) so users don't have to repeat themselves.
    """
    confidence, value = await calculate_confidence(db, user_id, dimension, course_id)

    # Fast-path: explicit signals promote on first occurrence
    if value is not None:
        has_explicit = await db.scalar(
            select(func.count(PreferenceSignal.id)).where(
                PreferenceSignal.user_id == user_id,
                PreferenceSignal.dimension == dimension,
                PreferenceSignal.value == value,
                PreferenceSignal.signal_type == "explicit",
                PreferenceSignal.dismissed_at.is_(None),
            ).where(
                *([PreferenceSignal.course_id == course_id] if course_id else [PreferenceSignal.course_id.is_(None)])
            )
        )
        if has_explicit:
            confidence = max(confidence, 0.5)

    if confidence < PROMOTION_THRESHOLD or value is None:
        return None

    # Upsert preference (race-condition safe)
    scope = "course" if course_id else "global"
    query = select(UserPreference).where(
        UserPreference.user_id == user_id,
        UserPreference.dimension == dimension,
        UserPreference.scope == scope,
    )
    if course_id:
        query = query.where(UserPreference.course_id == course_id)

    result = await db.execute(query)
    existing = result.scalar_one_or_none()

    if existing:
        if existing.dismissed_at is not None:
            return None
        existing.value = value
        existing.confidence = confidence
        existing.source = "behavior"
        await db.flush()
        return existing

    # No existing row — try to insert, handle race where another
    # request inserts the same row between our SELECT and INSERT.
    new_pref = UserPreference(
        user_id=user_id,
        course_id=course_id,
        scope=scope,
        dimension=dimension,
        value=value,
        source="behavior",
        confidence=confidence,
    )
    db.add(new_pref)
    try:
        await db.flush()
        return new_pref
    except IntegrityError:
        await db.rollback()
        # Another request inserted first — fetch and update
        result = await db.execute(query)
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
            existing.confidence = confidence
            existing.source = "behavior"
            await db.flush()
            return existing
        raise  # Unexpected — re-raise
