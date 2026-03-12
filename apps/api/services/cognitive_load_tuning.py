"""Lightweight per-user cognitive load weight auto-tuning (Track 2.4).

Queries resolved InterventionOutcome rows to compute per-signal effectiveness
rates, then applies Bayesian-style weight adjustments (+/-10%) within bounds.

Stores per-user weights in AgentKV. Requires at least 20 resolved outcomes
before adjustments begin.
"""

import logging
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings

logger = logging.getLogger(__name__)

_NAMESPACE = "cognitive_load"
_KEY = "signal_weights"
_MIN_SAMPLES = 20
_ADJUSTMENT_RATE = 0.10  # 10% adjustment per tuning cycle
_MAX_DEVIATION = 0.50    # Weights can deviate +/-50% from defaults


# Default weights from config — used as bounds anchors
def _default_weights() -> dict[str, float]:
    return {
        "fatigue": settings.cognitive_load_weight_fatigue,
        "session_length": settings.cognitive_load_weight_session_length,
        "errors": settings.cognitive_load_weight_errors,
        "brevity": settings.cognitive_load_weight_brevity,
        "help_seeking": settings.cognitive_load_weight_help_seeking,
        "quiz_performance": settings.cognitive_load_weight_quiz_performance,
        "answer_hesitation": settings.cognitive_load_weight_answer_hesitation,
        "nlp_affect": settings.cognitive_load_weight_nlp_affect,
        "relative_baseline": settings.cognitive_load_weight_relative_baseline,
        "wrong_streak": settings.cognitive_load_weight_wrong_streak,
        "message_gap": settings.cognitive_load_weight_message_gap,
        "repeated_errors": settings.cognitive_load_weight_repeated_errors,
    }


async def get_user_weights(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, float] | None:
    """Get per-user adjusted weights from AgentKV, or None for defaults."""
    try:
        from models.agent_kv import AgentKV
        result = await db.execute(
            select(AgentKV.value_json).where(
                AgentKV.user_id == user_id,
                AgentKV.namespace == _NAMESPACE,
                AgentKV.key == _KEY,
            )
        )
        row = result.scalar_one_or_none()
        return row if isinstance(row, dict) else None
    except Exception:
        logger.warning("Failed to load user cognitive load weights for %s", user_id, exc_info=True)
        return None


async def adjust_signal_weights(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, float] | None:
    """Compute and store adjusted weights based on intervention effectiveness.

    Returns the adjusted weights dict, or None if insufficient data.
    """
    from models.intervention_outcome import InterventionOutcome

    # Count total resolved outcomes
    total_result = await db.execute(
        select(func.count()).select_from(InterventionOutcome).where(
            InterventionOutcome.user_id == user_id,
            InterventionOutcome.resolved_at.isnot(None),
        )
    )
    total = total_result.scalar() or 0
    if total < _MIN_SAMPLES:
        return None

    # Count effective vs total per signal_source
    # Use case() for SQLite compatibility (no native bool→int cast)
    from sqlalchemy import case
    rows = await db.execute(
        select(
            InterventionOutcome.signal_source,
            func.count().label("total"),
            func.sum(case(
                (InterventionOutcome.was_effective == True, 1),  # noqa: E712
                else_=0,
            )).label("effective"),
        )
        .where(
            InterventionOutcome.user_id == user_id,
            InterventionOutcome.resolved_at.isnot(None),
            InterventionOutcome.was_effective.isnot(None),
        )
        .group_by(InterventionOutcome.signal_source)
    )

    effectiveness: dict[str, float] = {}
    for row in rows.fetchall():
        source = row[0]
        count = row[1]
        eff_count = row[2] or 0
        if count >= 5:  # Need at least 5 samples per signal
            effectiveness[source] = eff_count / count

    if not effectiveness:
        return None

    # Map signal_source to weight keys
    _SOURCE_TO_WEIGHT = {
        "cognitive_load": ["fatigue", "session_length", "errors", "brevity"],
        "nlp_affect": ["nlp_affect"],
        "frustration": ["help_seeking", "nlp_affect"],
        "cognitive_recovery": ["fatigue", "session_length"],
    }

    defaults = _default_weights()
    current = (await get_user_weights(db, user_id)) or dict(defaults)

    for source, rate in effectiveness.items():
        weight_keys = _SOURCE_TO_WEIGHT.get(source, [])
        for wk in weight_keys:
            if wk not in defaults:
                continue
            default_val = defaults[wk]
            cur_val = current.get(wk, default_val)

            if rate < 0.40:
                # Low effectiveness — reduce weight
                cur_val *= (1 - _ADJUSTMENT_RATE)
            elif rate > 0.70:
                # High effectiveness — increase weight
                cur_val *= (1 + _ADJUSTMENT_RATE)
            # else: 40-70% — no change

            # Clamp to bounds
            lower = default_val * (1 - _MAX_DEVIATION)
            upper = default_val * (1 + _MAX_DEVIATION)
            current[wk] = round(max(lower, min(upper, cur_val)), 4)

    # Store in AgentKV
    try:
        from models.agent_kv import AgentKV
        result = await db.execute(
            select(AgentKV).where(
                AgentKV.user_id == user_id,
                AgentKV.namespace == _NAMESPACE,
                AgentKV.key == _KEY,
            )
        )
        kv = result.scalar_one_or_none()
        if kv:
            kv.value_json = current
            kv.version = (kv.version or 0) + 1
        else:
            db.add(AgentKV(
                user_id=user_id,
                namespace=_NAMESPACE,
                key=_KEY,
                value_json=current,
                version=1,
            ))
        await db.flush()
        logger.info("Adjusted cognitive load weights for user %s: %s", user_id, current)
    except Exception:
        logger.warning("Failed to persist adjusted weights", exc_info=True)

    return current
