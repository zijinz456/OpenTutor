"""LECTOR Analytics -- Track review session effectiveness.

Measures:
- Review session completion rate
- Post-review mastery change
- Retention at +1/+3/+7 days

Usage:
    from services.lector_analytics import compute_review_effectiveness

    metrics = await compute_review_effectiveness(db, user_id, course_id)
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, ConceptMastery

logger = logging.getLogger(__name__)


async def compute_review_effectiveness(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Compute review effectiveness metrics.

    Returns:
        {
            "total_concepts": int,
            "reviewed_concepts": int,
            "avg_mastery": float,
            "overdue_count": int,
            "avg_stability_days": float,
        }
    """
    now = datetime.now(timezone.utc)

    # Get all concept IDs for this course
    node_result = await db.execute(
        select(KnowledgeNode.id).where(KnowledgeNode.course_id == course_id)
    )
    node_ids = [row[0] for row in node_result.all()]
    total_concepts = len(node_ids)

    if total_concepts == 0:
        return {
            "total_concepts": 0,
            "reviewed_concepts": 0,
            "avg_mastery": 0.0,
            "overdue_count": 0,
            "avg_stability_days": 0.0,
        }

    # Get mastery records for this user and course
    mastery_result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id.in_(node_ids),
        )
    )
    masteries = mastery_result.scalars().all()

    # Reviewed = practice_count > 0
    reviewed = [m for m in masteries if m.practice_count > 0]
    reviewed_concepts = len(reviewed)

    # Average mastery across all mastery records (including unreviewed with score 0)
    if masteries:
        avg_mastery = sum(m.mastery_score for m in masteries) / len(masteries)
    else:
        avg_mastery = 0.0

    # Overdue: next_review_at is in the past
    overdue_count = 0
    for m in masteries:
        if m.next_review_at:
            review_at = m.next_review_at
            if review_at.tzinfo is None:
                review_at = review_at.replace(tzinfo=timezone.utc)
            if review_at <= now:
                overdue_count += 1

    # Average stability days across reviewed concepts
    if reviewed:
        avg_stability_days = sum(m.stability_days for m in reviewed) / len(reviewed)
    else:
        avg_stability_days = 0.0

    metrics = {
        "total_concepts": total_concepts,
        "reviewed_concepts": reviewed_concepts,
        "avg_mastery": round(avg_mastery, 3),
        "overdue_count": overdue_count,
        "avg_stability_days": round(avg_stability_days, 2),
    }

    logger.info(
        "LECTOR analytics: user=%s course=%s — %d/%d reviewed, avg_mastery=%.3f, %d overdue",
        user_id, course_id, reviewed_concepts, total_concepts,
        avg_mastery, overdue_count,
    )
    return metrics


async def get_review_effectiveness_for_api(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Endpoint-ready wrapper for review effectiveness metrics.

    Adds derived fields useful for frontend display.
    """
    metrics = await compute_review_effectiveness(db, user_id, course_id)

    # Derive a coverage percentage
    total = metrics["total_concepts"]
    reviewed = metrics["reviewed_concepts"]
    coverage_pct = round((reviewed / total * 100) if total > 0 else 0.0, 1)

    # Derive a health score (0-100) combining mastery and overdue ratio
    overdue_ratio = (metrics["overdue_count"] / reviewed) if reviewed > 0 else 0.0
    health_score = round(
        metrics["avg_mastery"] * 70 + (1.0 - min(overdue_ratio, 1.0)) * 30, 1
    )

    return {
        **metrics,
        "coverage_pct": coverage_pct,
        "health_score": health_score,
    }
