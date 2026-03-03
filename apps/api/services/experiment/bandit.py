"""Thompson Sampling bandit for adaptive teaching strategy selection.

Uses BootstrappedTS from contextualbandits to learn the best teaching
strategy per student context.  Falls back to uniform random when the
library is unavailable.

Phase 4: Learning Style Discovery
"""

import logging
import json
import uuid
from typing import Any

try:
    import numpy as np
except ImportError:
    np = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

TEACHING_STRATEGIES = [
    "socratic_questioning",   # Socratic questions to guide thinking
    "worked_examples",        # Detailed step-by-step worked examples
    "visual_analogy",         # Visual analogies and diagrams
    "step_by_step",           # Incremental decomposition
    "example_heavy",          # Many concrete examples
]

# Feature names for the context vector
CONTEXT_FEATURES = [
    "mastery_score",        # Current topic mastery (0-1)
    "difficulty_level",     # Problem difficulty (0-1)
    "topic_familiarity",    # Familiarity with topic (0-1)
    "session_length",       # Minutes in current session (normalized 0-1)
    "recent_accuracy",      # Recent quiz accuracy (0-1)
    "help_request_count",   # Number of help requests (normalized 0-1)
]

# Global singleton — initialized lazily
_bandit_cache: dict[str, Any] = {}


def _make_bandit():
    """Create a fresh BootstrappedTS bandit or fallback."""
    try:
        from contextualbandits.online import BootstrappedTS
        from sklearn.linear_model import SGDClassifier

        return BootstrappedTS(
            nchoices=len(TEACHING_STRATEGIES),
            batch_train=True,
            base_algorithm=SGDClassifier(loss="log_loss", random_state=42),
            nsamples=10,
        )
    except ImportError:
        logger.warning("contextualbandits not installed — using random strategy selection")
        return None


def _get_user_bandit(user_id: uuid.UUID) -> Any:
    """Get or create a per-user bandit instance."""
    key = str(user_id)
    if key not in _bandit_cache:
        _bandit_cache[key] = _make_bandit()
    return _bandit_cache[key]


def build_context_vector(
    mastery_score: float = 0.5,
    difficulty_level: float = 0.5,
    topic_familiarity: float = 0.5,
    session_length_minutes: float = 0.0,
    recent_accuracy: float = 0.5,
    help_request_count: int = 0,
) -> "np.ndarray":
    """Build a normalized context feature vector."""
    if np is None:
        raise RuntimeError("numpy is required for bandit context vectors")
    return np.array([
        min(1.0, max(0.0, mastery_score)),
        min(1.0, max(0.0, difficulty_level)),
        min(1.0, max(0.0, topic_familiarity)),
        min(1.0, max(0.0, session_length_minutes / 60.0)),  # Normalize to 0-1
        min(1.0, max(0.0, recent_accuracy)),
        min(1.0, max(0.0, help_request_count / 10.0)),  # Normalize to 0-1
    ], dtype=np.float64).reshape(1, -1)


def select_strategy(user_id: uuid.UUID, context: "np.ndarray") -> tuple[str, int]:
    """Select the best teaching strategy for the given context.

    Returns (strategy_name, strategy_index).
    """
    bandit = _get_user_bandit(user_id)
    if bandit is None or np is None:
        # Fallback: uniform random
        import random
        idx = random.randrange(len(TEACHING_STRATEGIES))
        return TEACHING_STRATEGIES[idx], idx

    try:
        idx = int(bandit.predict(context)[0])
        return TEACHING_STRATEGIES[idx], idx
    except Exception:
        # Bandit not yet trained — random selection
        import random
        idx = random.randrange(len(TEACHING_STRATEGIES))
        return TEACHING_STRATEGIES[idx], idx


def observe_reward(
    user_id: uuid.UUID,
    context: "np.ndarray",
    strategy_idx: int,
    reward: float,
) -> None:
    """Observe the reward for a chosen strategy.

    reward: 1.0 if student answered correctly after teaching, 0.0 otherwise.
    """
    bandit = _get_user_bandit(user_id)
    if bandit is None:
        return

    try:
        bandit.partial_fit(
            context,
            np.array([strategy_idx]),
            np.array([reward]),
        )
    except Exception as e:
        logger.debug("Bandit partial_fit failed: %s", e)


async def select_strategy_for_context(
    db: "AsyncSession",
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    mastery_score: float = 0.5,
    difficulty_level: float = 0.5,
) -> dict:
    """High-level convenience: select a strategy with DB-derived features.

    Returns a dict with strategy name, index, and context vector.
    """
    # Build context from available data
    recent_accuracy = 0.5
    help_requests = 0

    try:
        from services.analytics.events import get_learning_events
        recent_events = await get_learning_events(
            db, user_id, course_id=course_id, verb="answered", limit=10,
        )
        if recent_events:
            correct = sum(1 for e in recent_events if e.success)
            recent_accuracy = correct / len(recent_events)
    except Exception:
        pass

    context = build_context_vector(
        mastery_score=mastery_score,
        difficulty_level=difficulty_level,
        recent_accuracy=recent_accuracy,
        help_request_count=help_requests,
    )

    strategy_name, strategy_idx = select_strategy(user_id, context)

    return {
        "strategy": strategy_name,
        "strategy_idx": strategy_idx,
        "context_vector": context.tolist(),
    }


async def record_strategy_outcome(
    user_id: uuid.UUID,
    strategy_idx: int,
    context_vector: list[list[float]],
    correct: bool,
) -> None:
    """Record the outcome of a teaching strategy for bandit learning."""
    reward = 1.0 if correct else 0.0
    if np is None:
        return
    context = np.array(context_vector, dtype=np.float64)
    observe_reward(user_id, context, strategy_idx, reward)
