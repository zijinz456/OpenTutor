"""Course completion forecaster.

Predicts when a student will complete mastery of all concepts in a course
based on their current learning velocity and remaining unmastered concepts.

Provides three estimates:
- optimistic: based on peak velocity
- expected: based on average velocity
- pessimistic: based on minimum velocity (or slower trend)
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import ConceptMastery, KnowledgeNode
from services.learning_science.velocity_tracker import MASTERY_THRESHOLD, compute_velocity

logger = logging.getLogger(__name__)


async def forecast_completion(
    db: AsyncSession,
    course_id: uuid.UUID,
) -> dict:
    """Forecast course completion date based on learning velocity.

    Returns:
        {
            "is_complete": bool,
            "concepts_remaining": int,
            "avg_gap": float,              # average mastery deficit for unmastered concepts
            "optimistic_days": float | None,
            "expected_days": float | None,
            "pessimistic_days": float | None,
            "optimistic_date": str | None, # ISO date
            "expected_date": str | None,
            "pessimistic_date": str | None,
            "confidence": "high" | "medium" | "low",
        }
    """
    velocity = await compute_velocity(db, course_id, window_days=14)
    total = velocity["concepts_total"]
    mastered = velocity["concepts_mastered"]
    remaining = total - mastered

    if total == 0:
        return _empty_forecast()

    if remaining == 0:
        return {
            "is_complete": True,
            "concepts_remaining": 0,
            "avg_gap": 0.0,
            "optimistic_days": 0,
            "expected_days": 0,
            "pessimistic_days": 0,
            "optimistic_date": datetime.now(timezone.utc).isoformat(),
            "expected_date": datetime.now(timezone.utc).isoformat(),
            "pessimistic_date": datetime.now(timezone.utc).isoformat(),
            "confidence": "high",
        }

    # Average mastery gap for unmastered concepts
    result = await db.execute(
        select(func.avg(ConceptMastery.mastery_score))
        .join(KnowledgeNode, ConceptMastery.knowledge_node_id == KnowledgeNode.id)
        .where(
            KnowledgeNode.course_id == str(course_id),
            ConceptMastery.mastery_score < MASTERY_THRESHOLD,
        )
    )
    avg_unmastered = float(result.scalar() or 0.0)
    avg_gap = MASTERY_THRESHOLD - avg_unmastered

    cpd = velocity["concepts_per_day"]
    now = datetime.now(timezone.utc)

    if cpd <= 0:
        # No positive velocity — can't predict
        return {
            "is_complete": False,
            "concepts_remaining": remaining,
            "avg_gap": round(avg_gap, 3),
            "optimistic_days": None,
            "expected_days": None,
            "pessimistic_days": None,
            "optimistic_date": None,
            "expected_date": None,
            "pessimistic_date": None,
            "confidence": "low",
        }

    # Estimate days based on velocity variants
    expected_days = remaining / cpd
    optimistic_days = expected_days * 0.6  # 40% faster
    pessimistic_days = expected_days * 1.8  # 80% slower

    # Adjust based on trend
    if velocity["velocity_trend"] == "accelerating":
        optimistic_days *= 0.8
        expected_days *= 0.9
    elif velocity["velocity_trend"] == "decelerating":
        expected_days *= 1.2
        pessimistic_days *= 1.3

    # Confidence based on data availability
    confidence = "medium"
    if velocity["concepts_per_day"] > 0 and mastered >= 5:
        confidence = "high"
    elif mastered < 2:
        confidence = "low"

    return {
        "is_complete": False,
        "concepts_remaining": remaining,
        "avg_gap": round(avg_gap, 3),
        "optimistic_days": round(optimistic_days, 1),
        "expected_days": round(expected_days, 1),
        "pessimistic_days": round(pessimistic_days, 1),
        "optimistic_date": (now + timedelta(days=optimistic_days)).date().isoformat(),
        "expected_date": (now + timedelta(days=expected_days)).date().isoformat(),
        "pessimistic_date": (now + timedelta(days=pessimistic_days)).date().isoformat(),
        "confidence": confidence,
    }


def _empty_forecast() -> dict:
    return {
        "is_complete": False,
        "concepts_remaining": 0,
        "avg_gap": 0.0,
        "optimistic_days": None,
        "expected_days": None,
        "pessimistic_days": None,
        "optimistic_date": None,
        "expected_date": None,
        "pessimistic_date": None,
        "confidence": "low",
    }
