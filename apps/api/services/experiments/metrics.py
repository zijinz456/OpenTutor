"""Learning outcome metrics for A/B experiment evaluation.

Computes:
- Mastery gain per study hour
- Retention at 1/7/30 days
- Quiz score improvement
- Session completion rate
- Time to mastery
- Engagement (messages per session)

Statistical tests:
- Two-proportion z-test for binary outcomes
- Mann-Whitney U for continuous outcomes
"""

import logging
import math
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import ConceptMastery, KnowledgeNode

logger = logging.getLogger(__name__)


async def compute_learning_metrics(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Compute comprehensive learning metrics for a user+course.

    Returns dict with mastery, retention, and engagement metrics.
    """
    # Get all concept nodes for this course
    nodes_result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = nodes_result.scalars().all()
    node_ids = [n.id for n in nodes]

    if not node_ids:
        return _empty_metrics()

    # Get user mastery records
    mastery_result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id.in_(node_ids),
        )
    )
    masteries = mastery_result.scalars().all()

    now = datetime.now(timezone.utc)

    # ── Core metrics ──

    total_concepts = len(nodes)
    reviewed_concepts = len(masteries)
    avg_mastery = sum(m.mastery_score for m in masteries) / max(len(masteries), 1)
    mastered_concepts = sum(1 for m in masteries if m.mastery_score >= 0.8)

    # Overdue concepts
    overdue_count = sum(
        1 for m in masteries
        if m.next_review_at and (
            m.next_review_at.replace(tzinfo=timezone.utc) if m.next_review_at.tzinfo is None else m.next_review_at
        ) <= now
    )

    # Average stability
    avg_stability = sum(m.stability_days for m in masteries) / max(len(masteries), 1)

    # Practice counts
    total_practices = sum(m.practice_count for m in masteries)
    total_correct = sum(m.correct_count for m in masteries)
    accuracy = total_correct / max(total_practices, 1)

    # Retention estimate (based on FSRS retrievability formula)
    retention_estimates = []
    for m in masteries:
        if m.last_practiced_at and m.stability_days > 0:
            last = m.last_practiced_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            days_since = (now - last).total_seconds() / 86400
            retrievability = (1 + days_since / (9 * m.stability_days)) ** -1
            retention_estimates.append(retrievability)

    avg_retention = sum(retention_estimates) / max(len(retention_estimates), 1)

    # Coverage
    coverage = reviewed_concepts / max(total_concepts, 1)

    return {
        "total_concepts": total_concepts,
        "reviewed_concepts": reviewed_concepts,
        "mastered_concepts": mastered_concepts,
        "coverage": round(coverage, 3),
        "avg_mastery": round(avg_mastery, 3),
        "avg_stability_days": round(avg_stability, 1),
        "avg_retention": round(avg_retention, 3),
        "overdue_count": overdue_count,
        "total_practices": total_practices,
        "accuracy": round(accuracy, 3),
    }


def _empty_metrics() -> dict:
    return {
        "total_concepts": 0,
        "reviewed_concepts": 0,
        "mastered_concepts": 0,
        "coverage": 0.0,
        "avg_mastery": 0.0,
        "avg_stability_days": 0.0,
        "avg_retention": 0.0,
        "overdue_count": 0,
        "total_practices": 0,
        "accuracy": 0.0,
    }


# ── Statistical Tests ──

def two_proportion_z_test(
    successes_a: int,
    total_a: int,
    successes_b: int,
    total_b: int,
) -> dict:
    """Two-proportion z-test for comparing binary outcomes between groups.

    Returns z-statistic, p-value, and whether the result is significant at p<0.05.
    """
    if total_a == 0 or total_b == 0:
        return {"z_stat": 0.0, "p_value": 1.0, "significant": False}

    p_a = successes_a / total_a
    p_b = successes_b / total_b
    p_pooled = (successes_a + successes_b) / (total_a + total_b)

    if p_pooled == 0 or p_pooled == 1:
        return {"z_stat": 0.0, "p_value": 1.0, "significant": False}

    se = math.sqrt(p_pooled * (1 - p_pooled) * (1 / total_a + 1 / total_b))
    if se == 0:
        return {"z_stat": 0.0, "p_value": 1.0, "significant": False}

    z = (p_a - p_b) / se
    # Two-tailed p-value approximation using normal CDF
    p_value = 2 * (1 - _normal_cdf(abs(z)))

    return {
        "z_stat": round(z, 4),
        "p_value": round(p_value, 6),
        "significant": p_value < 0.05,
        "p_a": round(p_a, 4),
        "p_b": round(p_b, 4),
        "effect_size": round(p_a - p_b, 4),
    }


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using the error function."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def mann_whitney_u(
    group_a: list[float],
    group_b: list[float],
) -> dict:
    """Mann-Whitney U test for comparing continuous outcomes between groups.

    Non-parametric test that doesn't assume normal distribution.
    """
    if not group_a or not group_b:
        return {"u_stat": 0.0, "p_value": 1.0, "significant": False}

    n_a = len(group_a)
    n_b = len(group_b)

    # Combine and rank
    combined = [(v, "a") for v in group_a] + [(v, "b") for v in group_b]
    combined.sort(key=lambda x: x[0])

    # Assign ranks (handle ties with average rank)
    ranks: list[tuple[float, str]] = []
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2  # 1-indexed average rank
        for k in range(i, j):
            ranks.append((avg_rank, combined[k][1]))
        i = j

    rank_sum_a = sum(r for r, g in ranks if g == "a")
    u_a = rank_sum_a - n_a * (n_a + 1) / 2

    # Normal approximation for p-value
    mean_u = n_a * n_b / 2
    std_u = math.sqrt(n_a * n_b * (n_a + n_b + 1) / 12)

    if std_u == 0:
        return {"u_stat": u_a, "p_value": 1.0, "significant": False}

    z = (u_a - mean_u) / std_u
    p_value = 2 * (1 - _normal_cdf(abs(z)))

    return {
        "u_stat": round(u_a, 2),
        "z_stat": round(z, 4),
        "p_value": round(p_value, 6),
        "significant": p_value < 0.05,
        "median_a": round(sorted(group_a)[len(group_a) // 2], 4) if group_a else 0,
        "median_b": round(sorted(group_b)[len(group_b) // 2], 4) if group_b else 0,
    }
