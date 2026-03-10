"""pyBKT-powered parameter estimation for Bayesian Knowledge Tracing.

Upgrades the simplified BKT in ``knowledge_tracer.py`` by using the pyBKT
library's EM algorithm to learn (prior, learns, guesses, slips) from real
student data.  Falls back to the heuristic estimator when pyBKT is
unavailable or data is insufficient.

Phase 4: Learning Digital Twin
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Minimum observations per concept to justify EM fitting
MIN_OBSERVATIONS_FOR_FIT = 15

# Weekly job runs every Saturday; keep params alive through the full cycle (+1 day grace).
_CACHE_TTL_SECONDS = 8 * 24 * 60 * 60


def _cache_key(user_id: uuid.UUID, course_id: uuid.UUID | None) -> str:
    return f"{user_id}:{course_id or 'all'}"


class _TrainedParamsCache:
    """Internal cache for fitted BKT params.

    Encapsulates TTL handling so callers use stable get/set/invalidate APIs
    instead of mutating module-level dicts directly.
    """

    def __init__(self) -> None:
        self._params_by_key: dict[str, dict[str, dict[str, float]]] = {}
        self._updated_at_by_key: dict[str, float] = {}

    def set(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID | None,
        fitted_params: dict[str, dict[str, float]],
        trained_at_ts: float | None = None,
    ) -> None:
        key = _cache_key(user_id, course_id)
        self._params_by_key[key] = fitted_params
        self._updated_at_by_key[key] = trained_at_ts if trained_at_ts is not None else time.time()

    def get(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID | None,
    ) -> dict[str, dict[str, float]] | None:
        key = _cache_key(user_id, course_id)
        cached_at = self._updated_at_by_key.get(key)
        if cached_at is None:
            # Defensive cleanup: a params entry without timestamp is invalid.
            self._params_by_key.pop(key, None)
            return None
        if time.time() - cached_at > _CACHE_TTL_SECONDS:
            self._params_by_key.pop(key, None)
            self._updated_at_by_key.pop(key, None)
            return None
        return self._params_by_key.get(key)

    def invalidate(
        self,
        *,
        user_id: uuid.UUID,
        course_id: uuid.UUID | None = None,
    ) -> None:
        if course_id is not None:
            key = _cache_key(user_id, course_id)
            self._params_by_key.pop(key, None)
            self._updated_at_by_key.pop(key, None)
            return
        prefix = f"{user_id}:"
        keys = [key for key in self._params_by_key if key.startswith(prefix)]
        for key in keys:
            self._params_by_key.pop(key, None)
            self._updated_at_by_key.pop(key, None)


_trained_params_cache = _TrainedParamsCache()


def set_trained_params_cache(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    fitted_params: dict[str, dict[str, float]],
    *,
    trained_at_ts: float | None = None,
) -> None:
    """Persist fitted params in cache."""
    _trained_params_cache.set(
        user_id=user_id,
        course_id=course_id,
        fitted_params=fitted_params,
        trained_at_ts=trained_at_ts,
    )


def get_trained_params_cache(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
) -> dict[str, dict[str, float]] | None:
    """Read cached fitted params for a user/course, honoring TTL."""
    return _trained_params_cache.get(user_id=user_id, course_id=course_id)


def invalidate_trained_params_cache(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> None:
    """Invalidate cache for one course or all courses for a user."""
    _trained_params_cache.invalidate(user_id=user_id, course_id=course_id)


async def _collect_response_data(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    days: int = 90,
) -> list[dict]:
    """Collect answer history from learning_events and practice_results.

    Returns list of dicts: [{concept, correct, timestamp}, ...]
    """
    from sqlalchemy import text as sa_text

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
        except (ValueError, KeyError, RuntimeError, TypeError) as e:
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

    set_trained_params_cache(user_id, course_id, fitted)

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
    params = get_trained_params_cache(user_id, course_id) or {}
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
