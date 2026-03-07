"""pyBKT-powered parameter estimation for Bayesian Knowledge Tracing.

Upgrades the simplified BKT in ``knowledge_tracer.py`` by using the pyBKT
library's EM algorithm to learn (prior, learns, guesses, slips) from real
student data.  Falls back to the heuristic estimator when pyBKT is
unavailable or data is insufficient.

Phase 4: Learning Digital Twin
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Minimum observations per concept to justify EM fitting
MIN_OBSERVATIONS_FOR_FIT = 15

# Cache fitted params per concept (invalidated on weekly retrain)
_fitted_params_cache: dict[str, dict[str, float]] = {}


async def _collect_response_data(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    days: int = 90,
) -> list[dict]:
    """Collect answer history from learning_events and practice_results.

    Returns list of dicts: [{concept, correct, timestamp}, ...]
    """
    from sqlalchemy import select, text as sa_text

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Pull from practice_results joined with problems for knowledge_points
    rows = await db.execute(
        sa_text("""
            SELECT
                pr.is_correct,
                pr.created_at,
                pp.knowledge_points,
                pp.content_node_id
            FROM practice_results pr
            JOIN practice_problems pp ON pr.problem_id = pp.id
            WHERE pr.user_id = :user_id
              AND pr.created_at >= :cutoff
              AND (:course_id IS NULL OR pp.course_id = :course_id)
            ORDER BY pr.created_at ASC
        """),
        {
            "user_id": str(user_id),
            "cutoff": cutoff,
            "course_id": str(course_id) if course_id else None,
        },
    )

    data = []
    for row in rows.fetchall():
        # knowledge_points can be a list or null
        concepts = row.knowledge_points or []
        if not concepts and row.content_node_id:
            concepts = [str(row.content_node_id)]
        for concept in concepts:
            data.append({
                "concept": str(concept),
                "correct": bool(row.is_correct),
                "timestamp": row.created_at,
            })

    return data


def _fit_with_pybkt(data: list[dict]) -> dict[str, dict[str, float]]:
    """Fit BKT parameters per concept using pyBKT EM algorithm.

    Returns {concept: {prior, learns, guesses, slips}} for concepts with
    enough data.
    """
    # Group by concept
    concept_data: dict[str, list[bool]] = {}
    for d in data:
        concept_data.setdefault(d["concept"], []).append(d["correct"])

    # No concept has enough data to justify EM fitting.
    if all(len(responses) < MIN_OBSERVATIONS_FOR_FIT for responses in concept_data.values()):
        return {}

    try:
        from pyBKT.models import Model
    except (ImportError, RuntimeError, OSError) as exc:
        logger.info("pyBKT unavailable — using heuristic BKT params (%s)", exc)
        return {}

    fitted = {}
    for concept, responses in concept_data.items():
        if len(responses) < MIN_OBSERVATIONS_FOR_FIT:
            continue

        try:
            # pyBKT expects data in a specific DataFrame format
            import pandas as pd

            df = pd.DataFrame({
                "user_id": [1] * len(responses),  # Single student
                "skill_name": [concept] * len(responses),
                "correct": [int(r) for r in responses],
                "order_id": list(range(1, len(responses) + 1)),
            })

            model = Model(seed=42)
            model.fit(data=df)

            # Extract learned parameters
            params = model.params()
            if params is not None and concept in params.index:
                row = params.loc[concept]
                fitted[concept] = {
                    "prior": float(row.get("prior", 0.1)),
                    "learns": float(row.get("learns", 0.2)),
                    "guesses": float(row.get("guesses", 0.25)),
                    "slips": float(row.get("slips", 0.1)),
                }
        except Exception as e:
            logger.warning("pyBKT fit failed for concept '%s': %s", concept, e)

    return fitted


async def train_bkt_params(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict[str, dict[str, float]]:
    """Train BKT parameters from student history.

    Called by weekly cron job.  Results are cached and used by
    ``compute_mastery_with_trained_params()``.
    """
    data = await _collect_response_data(db, user_id, course_id)
    if not data:
        return {}

    fitted = _fit_with_pybkt(data)

    # Cache results
    cache_key = f"{user_id}:{course_id or 'all'}"
    _fitted_params_cache[cache_key] = fitted

    logger.info(
        "BKT training complete: user=%s course=%s concepts_fitted=%d",
        user_id, course_id, len(fitted),
    )
    return fitted


def get_trained_params(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    concept: str,
) -> dict[str, float] | None:
    """Get cached trained params for a specific concept, or None."""
    cache_key = f"{user_id}:{course_id or 'all'}"
    params = _fitted_params_cache.get(cache_key, {})
    return params.get(concept)


def compute_mastery_with_trained_params(
    results: list[bool],
    concept: str,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    question_type: str | None = None,
) -> float:
    """Compute mastery using trained params if available, else heuristic.

    Drop-in replacement for ``knowledge_tracer.compute_mastery_from_sequence()``.
    """
    from services.learning_science.knowledge_tracer import (
        BKTParams,
        compute_mastery_from_sequence,
    )

    trained = get_trained_params(user_id, course_id, concept)
    if trained:
        params = BKTParams(
            p_l0=trained["prior"],
            p_t=trained["learns"],
            p_g=trained["guesses"],
            p_s=trained["slips"],
        )
        return compute_mastery_from_sequence(results, question_type, params=params)

    # Fallback to heuristic estimation
    return compute_mastery_from_sequence(results, question_type)
