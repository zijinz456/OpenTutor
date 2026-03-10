"""Learning velocity tracker.

Tracks the rate of concept mastery over time and provides statistics
for learning speed analysis and completion forecasting.

Metrics computed:
- concepts_mastered_per_session: How many concepts reach mastery (>= 0.8) per study session
- mastery_delta_per_day: Average change in mastery score per day
- learning_acceleration: Whether the student is speeding up or slowing down
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import ConceptMastery, KnowledgeNode
from models.mastery_snapshot import MasterySnapshot

logger = logging.getLogger(__name__)

MASTERY_THRESHOLD = 0.8


async def compute_velocity(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    window_days: int = 7,
) -> dict:
    """Compute learning velocity stats for a course over a time window.

    Returns:
        {
            "concepts_total": int,
            "concepts_mastered": int,
            "mastery_rate": float,         # fraction mastered
            "avg_mastery": float,          # average mastery score
            "concepts_per_day": float,     # mastery gain rate
            "velocity_trend": "accelerating" | "steady" | "decelerating",
            "window_days": int,
        }
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=window_days)

    # Current mastery state (join through KnowledgeNode to filter by course)
    result = await db.execute(
        select(
            func.count(ConceptMastery.id),
            func.sum(
                case(
                    (ConceptMastery.mastery_score >= MASTERY_THRESHOLD, 1),
                    else_=0,
                )
            ),
            func.avg(ConceptMastery.mastery_score),
        )
        .join(KnowledgeNode, ConceptMastery.knowledge_node_id == KnowledgeNode.id)
        .where(KnowledgeNode.course_id == str(course_id))
    )
    row = result.one()
    total = row[0] or 0
    mastered = row[1] or 0
    avg_mastery = float(row[2] or 0.0)

    if total == 0:
        return {
            "concepts_total": 0,
            "concepts_mastered": 0,
            "mastery_rate": 0.0,
            "avg_mastery": 0.0,
            "concepts_per_day": 0.0,
            "velocity_trend": "steady",
            "window_days": window_days,
        }

    # Compute mastery gain over the window using snapshots
    snapshots = await db.execute(
        select(MasterySnapshot)
        .where(
            MasterySnapshot.course_id == str(course_id),
            MasterySnapshot.recorded_at >= window_start,
        )
        .order_by(MasterySnapshot.recorded_at.asc())
    )
    snap_rows = snapshots.scalars().all()

    concepts_per_day = 0.0
    velocity_trend = "steady"

    if len(snap_rows) >= 2:
        first_snap = snap_rows[0]
        last_snap = snap_rows[-1]
        days_elapsed = max(
            (last_snap.recorded_at - first_snap.recorded_at).total_seconds() / 86400,
            0.1,
        )
        mastery_gain = last_snap.mastery_score - first_snap.mastery_score
        concepts_per_day = mastery_gain * total / days_elapsed

        # Split window in half to detect acceleration
        midpoint = len(snap_rows) // 2
        first_half = snap_rows[:midpoint]
        second_half = snap_rows[midpoint:]

        if first_half and second_half:
            first_half_gain = first_half[-1].mastery_score - first_half[0].mastery_score
            second_half_gain = second_half[-1].mastery_score - second_half[0].mastery_score

            if second_half_gain > first_half_gain * 1.2:
                velocity_trend = "accelerating"
            elif second_half_gain < first_half_gain * 0.8:
                velocity_trend = "decelerating"

    return {
        "concepts_total": total,
        "concepts_mastered": mastered,
        "mastery_rate": mastered / total if total else 0.0,
        "avg_mastery": round(avg_mastery, 3),
        "concepts_per_day": round(concepts_per_day, 2),
        "velocity_trend": velocity_trend,
        "window_days": window_days,
    }
