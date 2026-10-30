"""Cognitive load detection — behavioral signal analysis for adaptive difficulty.

Based on: "Cognitive Load Theory meets Deep Knowledge Tracing"
(Nature Scientific Reports, 2025, doi:10.1038/s41598-025-10497-x)

Computes a real-time cognitive load score (0.0–1.0) from behavioural signals
that are already in the database or in the message text: fatigue cues,
session length, error rate, message brevity, help-seeking, quiz accuracy,
answer time, wrong-answer streaks, message gaps and repeated errors.  No LLM
call is made.  The score is injected into the tutor's system prompt to adjust
explanation depth and feeds the block-decision rules.

Gated by ENABLE_COGNITIVE_LOAD (default off): when the flag is off the
orchestrator uses ``neutral_cognitive_load()`` instead of calling
``compute_cognitive_load``.  Signal weights live in config and sum to 1.0.
"""

import asyncio
import logging
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError as _SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings

logger = logging.getLogger(__name__)

# Track consecutive high-load messages for proactive intervention.
# Bounded to prevent unbounded memory growth with many students.
_MAX_TRACKING_SIZE = 200
_consecutive_high: dict[str, int] = {}  # user_id -> count
_consecutive_high_lock = asyncio.Lock()


def neutral_cognitive_load() -> dict:
    """The value prompt builders and block rules see when the feature is off."""
    return {
        "score": 0.0,
        "level": "low",
        "guidance": "",
        "signals": {},
        "consecutive_high": 0,
        "enabled": False,
    }

# Pre-compiled help-seeking patterns (word boundaries avoid false positives)
_HELP_PATTERNS = [
    re.compile(p) for p in [
        r"\bhelp\b", r"\bhint\b", r"\bexplain\b", r"\bdon'?t understand\b",
        r"\bconfused\b", r"\bstuck\b", r"\bhow do i\b",
    ]
]


async def compute_cognitive_load(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    fatigue_score: float = 0.0,
    session_messages: int = 0,
    user_message: str = "",
) -> dict:
    """Compute cognitive load from multiple behavioral signals.

    Returns dict with:
        score: float (0.0–1.0, higher = more loaded)
        level: str ("low" | "medium" | "high")
        guidance: str (prompt fragment for the tutor)
        signals: dict (breakdown of contributing signals)
    """
    signals: dict[str, float] = {}
    load = 0.0

    # ── Signal 1: Text-based fatigue (already computed) ──
    signals["fatigue"] = fatigue_score
    load += fatigue_score * settings.cognitive_load_weight_fatigue

    # ── Signal 2: Session length fatigue ──
    # Cognitive performance degrades after ~45 min of focused study
    session_fatigue = min(session_messages / settings.cognitive_load_session_messages_norm, 1.0)
    signals["session_length"] = session_fatigue
    load += session_fatigue * settings.cognitive_load_weight_session_length

    # ── Signal 3: Recent error rate ──
    try:
        from models.ingestion import WrongAnswer

        recent_errors = (
            await db.execute(
                select(func.count())
                .select_from(WrongAnswer)
                .where(
                    WrongAnswer.user_id == user_id,
                    WrongAnswer.course_id == course_id,
                    WrongAnswer.mastered == False,  # noqa: E712
                )
            )
        ).scalar() or 0
        # Normalize: 5+ unmastered errors = high load signal
        error_signal = min(recent_errors / settings.cognitive_load_error_count_norm, 1.0)
        signals["unmastered_errors"] = error_signal
        load += error_signal * settings.cognitive_load_weight_errors
    except (_SQLAlchemyError, OSError) as e:
        logger.exception("Cognitive load: error signal query failed")
        signals["unmastered_errors"] = 0.0

    # ── Signal 4: Message complexity drop ──
    # Short, terse messages may indicate frustration or overload
    msg_len = len(user_message.strip())
    if msg_len > 0:
        brevity_signal = max(0.0, 1.0 - (msg_len / settings.cognitive_load_brevity_length_norm))
        # Only count after the very first message (need at least some context)
        if session_messages > 1:
            signals["message_brevity"] = brevity_signal
            load += brevity_signal * settings.cognitive_load_weight_brevity
        else:
            signals["message_brevity"] = 0.0
    else:
        signals["message_brevity"] = 0.0

    # ── Signal 5: Help-seeking indicators ──
    _msg_lower = user_message.lower()
    help_signal = 1.0 if any(p.search(_msg_lower) for p in _HELP_PATTERNS) else 0.0
    signals["help_seeking"] = help_signal
    load += help_signal * settings.cognitive_load_weight_help_seeking

    # ── Signal 6: Recent quiz performance ──
    try:
        from models.progress import LearningProgress

        progress = (
            await db.execute(
                select(LearningProgress).where(
                    LearningProgress.user_id == user_id,
                    LearningProgress.course_id == course_id,
                )
            )
        ).scalar()
        if progress and progress.quiz_attempts and progress.quiz_attempts > 0:
            accuracy = progress.quiz_correct / progress.quiz_attempts
            # Low accuracy = high cognitive load
            perf_signal = max(0.0, 1.0 - (accuracy / settings.cognitive_load_quiz_accuracy_target))
            signals["quiz_performance"] = perf_signal
            load += perf_signal * settings.cognitive_load_weight_quiz_performance
        else:
            signals["quiz_performance"] = 0.0
    except (_SQLAlchemyError, OSError) as e:
        logger.exception("Cognitive load: quiz performance query failed")
        signals["quiz_performance"] = 0.0

    # ── Signal 7: Answer hesitation (quiz response timing) ──
    try:
        from models.practice import PracticeResult
        recent_times = await db.execute(
            select(PracticeResult.answer_time_ms)
            .where(
                PracticeResult.user_id == user_id,
                PracticeResult.answer_time_ms.isnot(None),
            )
            .order_by(PracticeResult.answered_at.desc())
            .limit(10)
        )
        times = [r[0] for r in recent_times.fetchall() if r[0] and r[0] > 0]
        if len(times) >= 3:
            import statistics
            median_ms = statistics.median(times)
            timing_signal = min(max(
                (median_ms - settings.cognitive_load_hesitation_min_ms)
                / settings.cognitive_load_hesitation_range_ms, 0.0), 1.0)
            signals["answer_hesitation"] = timing_signal
            load += timing_signal * settings.cognitive_load_weight_answer_hesitation
        else:
            signals["answer_hesitation"] = 0.0
    except (_SQLAlchemyError, OSError, ValueError) as e:
        logger.debug("Cognitive load: answer hesitation query failed: %s", e)
        signals["answer_hesitation"] = 0.0

    # ── Signal 8: Wrong answer streak ──
    # 3+ consecutive wrong answers signals frustration/overload
    try:
        from models.practice import PracticeResult as _PR
        recent_results = await db.execute(
            select(_PR.is_correct)
            .where(_PR.user_id == user_id)
            .order_by(_PR.answered_at.desc())
            .limit(10)
        )
        streak = 0
        for (correct,) in recent_results.fetchall():
            if not correct:
                streak += 1
            else:
                break
        wrong_streak_signal = min(streak / 5.0, 1.0)  # 5+ wrong = max
        signals["wrong_streak"] = wrong_streak_signal
        load += wrong_streak_signal * settings.cognitive_load_weight_wrong_streak
    except (_SQLAlchemyError, OSError):
        signals["wrong_streak"] = 0.0

    # ── Signal 9: Message gap (pause hesitation) ──
    # Long gaps between messages indicate the student is struggling
    try:
        from models.chat_message import ChatMessageLog as _CML
        from models.chat_session import ChatSession as _CS
        last_two = await db.execute(
            select(_CML.created_at)
            .join(_CS, _CS.id == _CML.session_id)
            .where(
                _CS.user_id == user_id,
                _CS.course_id == course_id,
                _CML.role == "user",
            )
            .order_by(_CML.created_at.desc())
            .limit(2)
        )
        timestamps = [r[0] for r in last_two.fetchall()]
        if len(timestamps) == 2:
            gap_seconds = (timestamps[0] - timestamps[1]).total_seconds()
            # 30s-300s gap = signal range; <30s or >300s (break) = no signal
            if 30 < gap_seconds < 300:
                gap_signal = min((gap_seconds - 30) / 270.0, 1.0)
            else:
                gap_signal = 0.0
        else:
            gap_signal = 0.0
        signals["message_gap"] = gap_signal
        load += gap_signal * settings.cognitive_load_weight_message_gap
    except (_SQLAlchemyError, OSError, AttributeError):
        signals["message_gap"] = 0.0

    # ── Signal 10: Repeated errors on same problems ──
    # Multiple wrong answers on the same problem signals deep confusion
    try:
        from models.ingestion import WrongAnswer as _WA2
        # Count problems with 2+ wrong attempts (still unmastered)
        sub = (
            select(_WA2.problem_id, func.count().label("cnt"))
            .where(
                _WA2.user_id == user_id,
                _WA2.course_id == course_id,
                _WA2.mastered == False,  # noqa: E712
            )
            .group_by(_WA2.problem_id)
            .having(func.count() >= 2)
            .subquery()
        )
        repeated = await db.execute(select(func.count()).select_from(sub))
        repeated_count = repeated.scalar() or 0
        repeated_signal = min(repeated_count / 3.0, 1.0)  # 3+ repeated = max
        signals["repeated_errors"] = repeated_signal
        load += repeated_signal * settings.cognitive_load_weight_repeated_errors
    except (_SQLAlchemyError, OSError, AttributeError):
        signals["repeated_errors"] = 0.0

    # Clamp
    score = max(0.0, min(load, 1.0))

    # Determine level
    if score > settings.cognitive_load_threshold_high:
        level = "high"
    elif score > settings.cognitive_load_threshold_medium:
        level = "medium"
    else:
        level = "low"

    # Track consecutive high-load messages for proactive intervention.
    # Use decay instead of hard reset: a single non-high message shouldn't
    # erase the history of sustained struggle. Decrement by 1 instead of reset to 0.
    async with _consecutive_high_lock:
        key = str(user_id)
        # Evict least-loaded entry if cache is full
        if key not in _consecutive_high and len(_consecutive_high) >= _MAX_TRACKING_SIZE:
            evict_key = min(_consecutive_high, key=_consecutive_high.get)
            del _consecutive_high[evict_key]
        if level == "high":
            _consecutive_high[key] = _consecutive_high.get(key, 0) + 1
        else:
            _consecutive_high[key] = max(0, _consecutive_high.get(key, 0) - 1)
        consecutive = _consecutive_high.get(key, 0)

    # Generate teaching guidance
    guidance = _build_guidance(level, score, signals, consecutive)

    return {
        "score": round(score, 3),
        "level": level,
        "guidance": guidance,
        "signals": {k: round(v, 3) for k, v in signals.items()},
        "consecutive_high": consecutive,
        "enabled": True,
    }


def _build_guidance(level: str, score: float, signals: dict, consecutive: int = 0) -> str:
    """Generate a prompt fragment that tells the tutor how to adapt."""
    if level == "low":
        return ""  # No special guidance needed

    parts = [f"\n## Cognitive Load: {level.upper()} (score: {score:.2f})"]

    if level == "high":
        parts.append(
            "The student is showing signs of cognitive overload. ADAPT your response:\n"
            "- Use SHORTER explanations (2-3 sentences max per concept)\n"
            "- Break complex ideas into ONE step at a time\n"
            "- Use concrete examples before abstract theory\n"
            "- Offer encouragement: 'This is a challenging topic, let's take it step by step'\n"
            "- If asking a question, make it simpler (recognition > recall)\n"
            "- Consider suggesting a brief break if the session has been long"
        )
        # Add specific signal-based advice
        if signals.get("unmastered_errors", 0) > 0.5:
            parts.append("- Focus on reviewing fundamentals before new material")
        if signals.get("session_length", 0) > 0.7:
            parts.append("- The session is getting long. Keep responses concise.")
        # Proactive intervention for sustained high load
        if consecutive >= 3:
            parts.append(
                "- IMPORTANT: The student has been struggling for several messages. "
                "Consider:\n"
                "  1. Suggesting a short break\n"
                "  2. Switching to a simpler scaffolded question\n"
                "  3. Providing a worked example instead of asking questions"
            )

    elif level == "medium":
        parts.append(
            "The student may be experiencing moderate cognitive load. Consider:\n"
            "- Slightly simpler explanations than default\n"
            "- Add a worked example alongside theory\n"
            "- Check understanding before adding complexity"
        )

    return "\n".join(parts)


def adjust_review_order_for_load(
    cognitive_load_score: float,
    cards: list[dict],
) -> list[dict]:
    """Reorder review cards based on cognitive load — easier cards first when loaded.

    Under high cognitive load, presenting easier (more stable) cards first
    lets the student build confidence before tackling harder material.
    """
    if cognitive_load_score < settings.cognitive_load_review_reorder_threshold or not cards:
        return cards
    # Sort by FSRS stability descending (most stable = easiest recall)
    return sorted(
        cards,
        key=lambda c: c.get("fsrs", {}).get("stability", 0),
        reverse=True,
    )
