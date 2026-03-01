"""Study timing analysis — learns user's preferred study schedule from habit logs.

Uses a weighted histogram approach with recency decay to identify
the peak study hour, then recommends sending notifications 30 minutes
before that peak to catch users before they start studying.
"""

import logging
import math
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.study_habit import StudyHabitLog

logger = logging.getLogger(__name__)

# Minimum sessions required for a reliable prediction
MIN_SESSIONS = 5

# Half-life in days for recency weighting (recent sessions matter more)
RECENCY_HALF_LIFE_DAYS = 14.0


async def compute_preferred_study_time(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> tuple[str | None, float]:
    """Compute the user's preferred study time from recent habit logs.

    Returns:
        (preferred_time, confidence) where:
        - preferred_time: "HH:MM" string (30 min before peak), or None if insufficient data
        - confidence: 0.0–1.0 indicating prediction reliability
    """
    result = await db.execute(
        select(StudyHabitLog)
        .where(StudyHabitLog.user_id == user_id)
        .order_by(StudyHabitLog.study_date.desc())
        .limit(30)
    )
    logs = result.scalars().all()

    if len(logs) < MIN_SESSIONS:
        logger.debug(
            "Insufficient study data for user %s (%d/%d sessions)",
            user_id, len(logs), MIN_SESSIONS,
        )
        return None, 0.0

    # Build weighted histogram of start hours (24 bins)
    histogram = [0.0] * 24

    # Most recent date for recency calculation
    most_recent = max(log.study_date for log in logs)

    for log in logs:
        days_ago = (most_recent - log.study_date).days
        # Exponential decay: weight = 2^(-days_ago / half_life)
        weight = math.pow(2, -days_ago / RECENCY_HALF_LIFE_DAYS)
        # Weight by duration (longer sessions are stronger signals)
        duration_weight = min(log.duration_minutes / 30.0, 3.0)  # Cap at 3x
        histogram[log.start_hour] += weight * duration_weight

    total_weight = sum(histogram)
    if total_weight == 0:
        return None, 0.0

    # Find peak hour
    peak_hour = max(range(24), key=lambda h: histogram[h])
    peak_weight = histogram[peak_hour]

    # Confidence: how concentrated is the distribution?
    # High confidence = most weight in peak ± 1 hour
    neighborhood = sum(histogram[(peak_hour + d) % 24] for d in [-1, 0, 1])
    confidence = min(neighborhood / total_weight, 1.0)

    # Scale confidence by number of sessions (more data = higher confidence)
    session_factor = min(len(logs) / 20.0, 1.0)
    confidence *= session_factor

    # Preferred time: 30 minutes before peak hour
    notify_hour = (peak_hour - 1) % 24
    notify_minute = 30

    preferred_time = f"{notify_hour:02d}:{notify_minute:02d}"

    logger.info(
        "Study timing for user %s: peak_hour=%d preferred_time=%s confidence=%.2f (n=%d)",
        user_id, peak_hour, preferred_time, confidence, len(logs),
    )

    return preferred_time, round(confidence, 3)
