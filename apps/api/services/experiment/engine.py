"""A/B testing experiment engine.

Handles:
1. Deterministic user-variant assignment (hash-based, sticky)
2. Experiment config resolution (merge variant config into agent context)
3. Metric recording and statistical analysis
4. Experiment lifecycle (create, activate, end, analyze)

References:
- Google Vizier: hash-based traffic splitting
- Optimizely: feature flags + experiment layering
- Statsig: Bayesian analysis for early stopping
"""

import hashlib
import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.experiment import Experiment, ExperimentAssignment, ExperimentEvent

logger = logging.getLogger(__name__)


def _hash_assignment(user_id: uuid.UUID, experiment_id: uuid.UUID) -> float:
    """Deterministic hash for user-experiment pair → [0.0, 1.0).

    Same user + same experiment always gets the same hash,
    ensuring sticky assignment without storing state first.
    """
    combined = f"{user_id}:{experiment_id}"
    h = hashlib.sha256(combined.encode()).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


async def get_active_experiments(
    db: AsyncSession,
    dimension: str | None = None,
) -> list[Experiment]:
    """Get all active experiments, optionally filtered by dimension."""
    query = select(Experiment).where(Experiment.is_active.is_(True))
    if dimension:
        query = query.where(Experiment.dimension == dimension)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_user_variant(
    db: AsyncSession,
    user_id: uuid.UUID,
    experiment: Experiment,
) -> str | None:
    """Get or assign a variant for a user in an experiment.

    Uses hash-based deterministic assignment:
    1. Check if user already assigned → return existing
    2. Check if user falls within traffic fraction → assign
    3. Return None if user not in experiment
    """
    # Check existing assignment
    existing = await db.execute(
        select(ExperimentAssignment).where(
            ExperimentAssignment.user_id == user_id,
            ExperimentAssignment.experiment_id == experiment.id,
        )
    )
    assignment = existing.scalar_one_or_none()
    if assignment:
        return assignment.variant_id

    # Hash-based traffic split
    h = _hash_assignment(user_id, experiment.id)
    if h >= experiment.traffic_fraction:
        return None  # User not in experiment

    # Assign variant based on hash
    variants = experiment.variants or []
    if not variants:
        return None

    variant_idx = int(h * len(variants) / experiment.traffic_fraction) % len(variants)
    variant_id = variants[variant_idx].get("id", f"variant_{variant_idx}")

    # Store assignment
    new_assignment = ExperimentAssignment(
        experiment_id=experiment.id,
        user_id=user_id,
        variant_id=variant_id,
    )
    db.add(new_assignment)
    await db.flush()

    logger.info(
        "User %s assigned to variant '%s' in experiment '%s'",
        user_id, variant_id, experiment.name,
    )
    return variant_id


async def get_experiment_config(
    db: AsyncSession,
    user_id: uuid.UUID,
    dimension: str,
) -> dict | None:
    """Get the experiment config for a user in a given dimension.

    Returns the variant's config dict, or None if no active experiment
    or user not enrolled.
    """
    experiments = await get_active_experiments(db, dimension)
    if not experiments:
        return None

    # Use first matching active experiment (could layer multiple)
    experiment = experiments[0]
    variant_id = await get_user_variant(db, user_id, experiment)
    if not variant_id:
        return None

    # Find variant config
    for variant in experiment.variants or []:
        if variant.get("id") == variant_id:
            return {
                "experiment_id": str(experiment.id),
                "experiment_name": experiment.name,
                "variant_id": variant_id,
                "config": variant.get("config", {}),
            }

    return None


async def record_metric(
    db: AsyncSession,
    experiment_id: uuid.UUID,
    user_id: uuid.UUID,
    variant_id: str,
    metric_name: str,
    metric_value: float,
    metadata: dict | None = None,
) -> None:
    """Record a metric event for experiment analysis."""
    event = ExperimentEvent(
        experiment_id=experiment_id,
        user_id=user_id,
        variant_id=variant_id,
        metric_name=metric_name,
        metric_value=metric_value,
        metadata_json=metadata,
    )
    db.add(event)
    await db.flush()


async def analyze_experiment(
    db: AsyncSession,
    experiment_id: uuid.UUID,
) -> dict:
    """Analyze experiment results with basic statistical testing.

    Returns per-variant metrics with means, counts, and
    a simple z-test for significance between control and treatment.
    """
    experiment_result = await db.execute(
        select(Experiment).where(Experiment.id == experiment_id)
    )
    experiment = experiment_result.scalar_one_or_none()
    if not experiment:
        return {"error": "Experiment not found"}

    # Get aggregated metrics per variant
    metrics_result = await db.execute(
        select(
            ExperimentEvent.variant_id,
            ExperimentEvent.metric_name,
            func.count(ExperimentEvent.id).label("count"),
            func.avg(ExperimentEvent.metric_value).label("mean"),
            func.stddev(ExperimentEvent.metric_value).label("stddev"),
        )
        .where(ExperimentEvent.experiment_id == experiment_id)
        .group_by(ExperimentEvent.variant_id, ExperimentEvent.metric_name)
    )
    rows = metrics_result.fetchall()

    # Build variant stats
    variant_stats: dict[str, dict[str, dict]] = {}
    for row in rows:
        vid = row.variant_id
        metric = row.metric_name
        if vid not in variant_stats:
            variant_stats[vid] = {}
        variant_stats[vid][metric] = {
            "count": row.count,
            "mean": round(float(row.mean or 0), 4),
            "stddev": round(float(row.stddev or 0), 4),
        }

    # Z-test between first two variants (control vs treatment) for primary metric
    significance = None
    variant_ids = list(variant_stats.keys())
    primary = experiment.primary_metric

    if len(variant_ids) >= 2:
        a = variant_stats.get(variant_ids[0], {}).get(primary, {})
        b = variant_stats.get(variant_ids[1], {}).get(primary, {})
        if a.get("count", 0) >= 10 and b.get("count", 0) >= 10:
            # Two-sample z-test
            mean_a, mean_b = a["mean"], b["mean"]
            std_a, std_b = a.get("stddev", 0), b.get("stddev", 0)
            n_a, n_b = a["count"], b["count"]
            se = math.sqrt((std_a**2 / n_a) + (std_b**2 / n_b)) if (std_a > 0 or std_b > 0) else 0

            if se > 0:
                z = (mean_b - mean_a) / se
                # Approximate p-value (two-tailed) using normal CDF
                p = 2 * (1 - _normal_cdf(abs(z)))
                significance = {
                    "z_score": round(z, 4),
                    "p_value": round(p, 6),
                    "significant": p < 0.05,
                    "winner": variant_ids[1] if z > 0 else variant_ids[0],
                    "effect_size": round(mean_b - mean_a, 4),
                }

    # User counts
    user_counts_result = await db.execute(
        select(
            ExperimentAssignment.variant_id,
            func.count(ExperimentAssignment.id).label("users"),
        )
        .where(ExperimentAssignment.experiment_id == experiment_id)
        .group_by(ExperimentAssignment.variant_id)
    )
    user_counts = {row.variant_id: row.users for row in user_counts_result.fetchall()}

    return {
        "experiment": {
            "id": str(experiment.id),
            "name": experiment.name,
            "dimension": experiment.dimension,
            "primary_metric": experiment.primary_metric,
            "is_active": experiment.is_active,
        },
        "variants": variant_stats,
        "user_counts": user_counts,
        "significance": significance,
    }


def _normal_cdf(x: float) -> float:
    """Approximate normal CDF using Abramowitz and Stegun formula."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


async def create_experiment(
    db: AsyncSession,
    name: str,
    dimension: str,
    variants: list[dict],
    description: str = "",
    traffic_fraction: float = 1.0,
    primary_metric: str = "response_quality",
) -> Experiment:
    """Create a new A/B test experiment."""
    exp = Experiment(
        name=name,
        description=description,
        dimension=dimension,
        variants=variants,
        traffic_fraction=traffic_fraction,
        primary_metric=primary_metric,
    )
    db.add(exp)
    await db.flush()
    return exp


async def end_experiment(
    db: AsyncSession,
    experiment_id: uuid.UUID,
) -> dict:
    """End an experiment and return final analysis."""
    result = await db.execute(
        select(Experiment).where(Experiment.id == experiment_id)
    )
    experiment = result.scalar_one_or_none()
    if not experiment:
        return {"error": "Not found"}

    experiment.is_active = False
    experiment.ended_at = datetime.now(timezone.utc)
    await db.flush()

    return await analyze_experiment(db, experiment_id)
