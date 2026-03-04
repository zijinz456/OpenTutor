"""Score prediction model — predicts exam performance and improvement potential.

Uses GradientBoostingRegressor when enough data exists, falls back to a
simple weighted heuristic for cold-start.

Phase 4: Learning Digital Twin
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Minimum training samples before using ML model
MIN_TRAINING_SAMPLES = 20

# In-memory model cache per user (retrained weekly)
_model_cache: dict[str, Any] = {}


def _build_features_from_state(state: dict) -> list[float]:
    """Extract a feature vector from a learning state dict.

    Must stay in sync with the training feature matrix in ``train_model``.
    """
    total_topics = max(int(state.get("total_topics", 10) or 10), 1)
    num_topics_mastered = min(
        max(int(state.get("num_topics_mastered", 0) or 0), 0),
        total_topics,
    )
    return [
        state.get("avg_mastery", 0.5),
        state.get("study_hours_last_7d", 0.0) / 20.0,  # Normalize
        state.get("quiz_accuracy", 0.5),
        state.get("days_until_exam", 30) / 60.0,  # Normalize
        state.get("review_consistency", 0.5),
        num_topics_mastered / total_topics,
        state.get("flashcard_retention", 0.5),
    ]


def _heuristic_predict(state: dict) -> dict:
    """Cold-start prediction using a weighted formula."""
    mastery = state.get("avg_mastery", 0.5)
    accuracy = state.get("quiz_accuracy", 0.5)
    consistency = state.get("review_consistency", 0.5)
    retention = state.get("flashcard_retention", 0.5)

    # Weighted combination
    predicted = (
        mastery * 0.35
        + accuracy * 0.30
        + consistency * 0.15
        + retention * 0.20
    ) * 100  # Scale to 0-100

    # Simulate: what if student studies 30 more minutes per day
    days = max(state.get("days_until_exam", 7), 1)
    extra_hours = 0.5 * days
    current_hours = state.get("study_hours_last_7d", 5.0)
    boost_factor = min(0.15, extra_hours / max(current_hours + extra_hours, 1) * 0.3)
    boosted = min(100.0, predicted * (1 + boost_factor))

    return {
        "predicted_score": round(predicted, 1),
        "confidence": "low",
        "with_extra_30min_daily": round(boosted, 1),
        "improvement_potential": round(boosted - predicted, 1),
        "model": "heuristic",
    }


async def gather_prediction_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Gather current learning state for prediction."""
    from sqlalchemy import func, select

    state: dict[str, Any] = {}

    # Average mastery from learning_progress
    try:
        from models.progress import LearningProgress

        result = await db.execute(
            select(func.avg(LearningProgress.mastery_score))
            .where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        )
        state["avg_mastery"] = float(result.scalar() or 0.5)
    except Exception:
        state["avg_mastery"] = 0.5

    # Quiz accuracy from recent practice results
    try:
        from models.practice import PracticeProblem, PracticeResult

        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        result = await db.execute(
            select(
                func.count(PracticeResult.id),
                func.sum(PracticeResult.is_correct.cast(int)),
            )
            .join(PracticeProblem, PracticeProblem.id == PracticeResult.problem_id)
            .where(
                PracticeResult.user_id == user_id,
                PracticeResult.answered_at >= cutoff,
                PracticeProblem.course_id == course_id,
            )
        )
        row = result.one()
        total = row[0] or 0
        correct = row[1] or 0
        state["quiz_accuracy"] = correct / max(total, 1)
    except Exception:
        state["quiz_accuracy"] = 0.5

    # Study hours (from learning events duration)
    try:
        from models.learning_event import LearningEvent

        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            select(func.sum(LearningEvent.duration_seconds))
            .where(
                LearningEvent.user_id == user_id,
                LearningEvent.course_id == course_id,
                LearningEvent.timestamp >= cutoff,
            )
        )
        total_seconds = result.scalar() or 0
        state["study_hours_last_7d"] = total_seconds / 3600.0
    except Exception:
        state["study_hours_last_7d"] = 3.0

    # Defaults for items not yet available
    state.setdefault("days_until_exam", 14)
    state.setdefault("review_consistency", 0.5)
    state.setdefault("num_topics_mastered", 0)
    state.setdefault("total_topics", 10)
    state.setdefault("flashcard_retention", 0.5)

    return state


async def predict_score(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    days_until_exam: int | None = None,
) -> dict:
    """Predict exam score for the student.

    Returns predicted score (0-100), confidence, and improvement potential.
    """
    state = await gather_prediction_state(db, user_id, course_id)
    if days_until_exam is not None:
        state["days_until_exam"] = days_until_exam

    # Check if we have a trained ML model
    cache_key = f"{user_id}:{course_id}"
    model = _model_cache.get(cache_key)

    if model is not None:
        try:
            import numpy as np

            features = np.array(_build_features_from_state(state)).reshape(1, -1)
            predicted = float(model.predict(features)[0])
            predicted = max(0.0, min(100.0, predicted))

            # Simulate extra study
            boosted_state = state.copy()
            boosted_state["study_hours_last_7d"] += 0.5 * max(state.get("days_until_exam", 7), 1)
            boosted_features = np.array(_build_features_from_state(boosted_state)).reshape(1, -1)
            boosted = float(model.predict(boosted_features)[0])
            boosted = max(0.0, min(100.0, boosted))

            return {
                "predicted_score": round(predicted, 1),
                "confidence": "medium",
                "with_extra_30min_daily": round(boosted, 1),
                "improvement_potential": round(boosted - predicted, 1),
                "model": "gradient_boosting",
            }
        except Exception as e:
            logger.warning("ML prediction failed, falling back to heuristic: %s", e)

    return _heuristic_predict(state)


async def train_model(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> bool:
    """Train a prediction model from historical data.

    Called by weekly cron job.  Returns True if training succeeded.
    """
    try:
        from sklearn.ensemble import GradientBoostingRegressor
        import numpy as np
    except ImportError:
        logger.info("scikit-learn not installed — score prediction uses heuristic only")
        return False

    # Gather historical snapshots for training
    # For now, use a simplified approach: generate synthetic training data
    # from the student's progression over time
    try:
        from sqlalchemy import select, func
        from models.mastery_snapshot import MasterySnapshot

        snapshots = await db.execute(
            select(MasterySnapshot)
            .where(
                MasterySnapshot.user_id == user_id,
                MasterySnapshot.course_id == course_id,
            )
            .order_by(MasterySnapshot.recorded_at.asc())
        )
        rows = snapshots.scalars().all()

        if len(rows) < MIN_TRAINING_SAMPLES:
            logger.info(
                "Not enough data for ML training (need %d, have %d)",
                MIN_TRAINING_SAMPLES, len(rows),
            )
            return False

        # Build training data from mastery snapshots using the same feature
        # semantics as inference, so model predictions remain interpretable.
        X = []
        y = []
        total_rows = len(rows)
        topics_mastered_so_far = 0
        for i, row in enumerate(rows):
            if row.mastery_score >= 0.7:
                topics_mastered_so_far += 1
            days_until_exam = max(total_rows - i, 1)
            review_consistency = max(0.1, 1.0 - (i / max(total_rows, 1)) * 0.5)
            flashcard_retention = 1.0 if row.gap_type in {None, "mastered"} else 0.55
            state = {
                "avg_mastery": row.mastery_score,
                "study_hours_last_7d": min(20.0, 2.0 + (i / max(total_rows, 1)) * 12.0),
                "quiz_accuracy": min(1.0, max(0.0, row.mastery_score)),
                "days_until_exam": days_until_exam,
                "review_consistency": review_consistency,
                "num_topics_mastered": topics_mastered_so_far,
                "total_topics": total_rows,
                "flashcard_retention": flashcard_retention,
            }
            X.append(_build_features_from_state(state))
            # Target: future mastery (next snapshot or current)
            future_idx = min(i + 5, total_rows - 1)
            y.append(rows[future_idx].mastery_score * 100)  # Scale to 0-100

        model = GradientBoostingRegressor(
            n_estimators=50,
            max_depth=3,
            learning_rate=0.1,
            random_state=42,
        )
        model.fit(np.array(X), np.array(y))

        cache_key = f"{user_id}:{course_id}"
        _model_cache[cache_key] = model
        logger.info("Score prediction model trained for user=%s course=%s", user_id, course_id)
        return True

    except Exception as e:
        logger.warning("Score prediction training failed: %s", e)
        return False
