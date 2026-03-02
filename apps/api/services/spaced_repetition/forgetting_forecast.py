"""Forgetting curve prediction using FSRS retrievability.

Uses R(t) = (1 + t/(9*S))^-1 to predict when each knowledge point
will drop below the retention threshold.
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.progress import LearningProgress
from models.content import CourseContentTree

logger = logging.getLogger(__name__)

# Default retention threshold (90% matches FSRS default)
_RETENTION_THRESHOLD = 0.90

# Warn threshold — below this, the knowledge point needs urgent review
_URGENT_THRESHOLD = 0.70


@dataclass
class ForgettingPrediction:
    """Prediction for a single knowledge point."""
    content_node_id: str | None
    title: str
    current_retrievability: float  # 0.0-1.0
    stability_days: float
    days_until_threshold: float  # days until recall drops below retention threshold
    predicted_drop_date: str  # ISO date
    urgency: str  # ok | warning | urgent | overdue
    last_reviewed: str | None
    mastery_score: float


from libs.datetime_utils import as_utc as _as_utc


def _retrievability(elapsed_days: float, stability: float) -> float:
    """FSRS retrievability: R(t) = (1 + t/(9*S))^-1"""
    if stability <= 0:
        return 0.0
    return pow(1 + elapsed_days / (9 * stability), -1)


def _days_until_retention(stability: float, threshold: float = _RETENTION_THRESHOLD) -> float:
    """Calculate days until retrievability drops to threshold.

    From R(t) = (1 + t/(9*S))^-1, solve for t:
    t = 9 * S * (1/R - 1)
    """
    if stability <= 0 or threshold <= 0 or threshold >= 1:
        return 0.0
    return 9 * stability * (1 / threshold - 1)


async def predict_forgetting(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Generate forgetting forecast for all reviewed knowledge points in a course."""
    # Get all progress entries with FSRS data
    result = await db.execute(
        select(LearningProgress, CourseContentTree.title)
        .outerjoin(CourseContentTree, LearningProgress.content_node_id == CourseContentTree.id)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
            LearningProgress.fsrs_reps > 0,  # Only items that have been reviewed
        )
    )
    rows = result.all()

    now = datetime.now(timezone.utc)
    predictions: list[dict] = []
    urgent_count = 0
    warning_count = 0

    for progress, title in rows:
        stability = progress.fsrs_stability
        last_review = progress.last_studied_at

        if not last_review or stability <= 0:
            continue

        elapsed_days = max((now - _as_utc(last_review)).total_seconds() / 86400, 0)
        current_r = _retrievability(elapsed_days, stability)

        # Days from last review until threshold
        total_days_to_threshold = _days_until_retention(stability, _RETENTION_THRESHOLD)
        remaining_days = max(total_days_to_threshold - elapsed_days, 0)

        # Determine urgency
        if current_r < _URGENT_THRESHOLD:
            urgency = "overdue"
            urgent_count += 1
        elif current_r < _RETENTION_THRESHOLD:
            urgency = "urgent"
            urgent_count += 1
        elif remaining_days < 2:
            urgency = "warning"
            warning_count += 1
        else:
            urgency = "ok"

        predicted_drop_date = (now + timedelta(days=remaining_days)).isoformat()

        predictions.append({
            "content_node_id": str(progress.content_node_id) if progress.content_node_id else None,
            "title": title or "Course-level",
            "current_retrievability": round(current_r, 3),
            "stability_days": round(stability, 1),
            "days_until_threshold": round(remaining_days, 1),
            "predicted_drop_date": predicted_drop_date,
            "urgency": urgency,
            "last_reviewed": _as_utc(last_review).isoformat() if last_review else None,
            "mastery_score": round(progress.mastery_score, 3),
        })

    # Sort by urgency (overdue first, then by days_until_threshold ascending)
    urgency_order = {"overdue": 0, "urgent": 1, "warning": 2, "ok": 3}
    predictions.sort(key=lambda p: (urgency_order.get(p["urgency"], 4), p["days_until_threshold"]))

    return {
        "course_id": str(course_id),
        "generated_at": now.isoformat(),
        "total_items": len(predictions),
        "urgent_count": urgent_count,
        "warning_count": warning_count,
        "predictions": predictions,
    }
