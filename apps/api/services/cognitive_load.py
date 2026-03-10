"""Cognitive load detection — behavioral signal analysis for adaptive difficulty.

Based on: "Cognitive Load Theory meets Deep Knowledge Tracing"
(Nature Scientific Reports, 2025, doi:10.1038/s41598-025-10497-x)

Computes a real-time cognitive load score (0.0–1.0) from existing behavioral
signals: fatigue text cues, session duration, error patterns, and message
characteristics. The score is injected into the tutor's system prompt to
dynamically adjust explanation depth and difficulty.

Signal weights are tuned for a single-user local deployment where we have
full session context (no multi-tenant noise).
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError as _SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings

logger = logging.getLogger(__name__)

# Track consecutive high-load messages for proactive intervention
_consecutive_high: dict[str, int] = {}  # user_id -> count


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
    session_fatigue = min(session_messages / 40.0, 1.0)  # ~40 messages ≈ 45 min
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
        error_signal = min(recent_errors / 5.0, 1.0)
        signals["unmastered_errors"] = error_signal
        load += error_signal * settings.cognitive_load_weight_errors
    except (_SQLAlchemyError, OSError) as e:
        logger.exception("Cognitive load: error signal query failed")
        signals["unmastered_errors"] = 0.0

    # ── Signal 4: Message complexity drop ──
    # Short, terse messages may indicate frustration or overload
    msg_len = len(user_message.strip())
    if msg_len > 0:
        brevity_signal = max(0.0, 1.0 - (msg_len / 100.0))  # <100 chars = some signal
        # Only count if we have session context (student was writing longer before)
        if session_messages > 3:
            signals["message_brevity"] = brevity_signal
            load += brevity_signal * settings.cognitive_load_weight_brevity
        else:
            signals["message_brevity"] = 0.0
    else:
        signals["message_brevity"] = 0.0

    # ── Signal 5: Help-seeking indicators ──
    # Detect explicit help-seeking in current message
    help_keywords = ["help", "hint", "explain", "don't understand", "confused", "stuck", "how do i"]
    help_signal = 1.0 if any(kw in user_message.lower() for kw in help_keywords) else 0.0
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
            perf_signal = max(0.0, 1.0 - (accuracy / 0.7))  # Below 70% = signal
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
            # 15s median = no signal, 60s+ median = full signal
            timing_signal = min(max((median_ms - 15000) / 45000, 0.0), 1.0)
            signals["answer_hesitation"] = timing_signal
            load += timing_signal * 0.10
        else:
            signals["answer_hesitation"] = 0.0
    except (_SQLAlchemyError, OSError, ValueError) as e:
        logger.debug("Cognitive load: answer hesitation query failed: %s", e)
        signals["answer_hesitation"] = 0.0

    # ── Signal 8: NLP-based affect analysis ──
    from services.cognitive_load_nlp import analyze_student_affect

    affect = await analyze_student_affect(user_message) if user_message else {}
    frustration = affect.get("frustration", 0.0)
    confusion = affect.get("confusion", 0.0)
    nlp_signal = frustration * 0.6 + confusion * 0.4  # Weighted combination
    signals["nlp_affect"] = nlp_signal
    load += nlp_signal * 0.15  # 15% weight for NLP signal

    # ── Signal 9: Relative baseline calibration ──
    from services.cognitive_load_calibrator import (
        get_or_create_baseline,
        compute_relative_load,
    )

    baseline = get_or_create_baseline(user_id)
    is_help = help_signal > 0
    relative = compute_relative_load(baseline, len(user_message), is_help)
    baseline.update(user_message, is_help)

    if relative["calibrated"]:
        for adj_name, adj_value in relative["adjustments"].items():
            signals[adj_name] = adj_value
            load += adj_value * 0.1

    # Clamp
    score = max(0.0, min(load, 1.0))

    # Determine level
    if score > settings.cognitive_load_threshold_high:
        level = "high"
    elif score > settings.cognitive_load_threshold_medium:
        level = "medium"
    else:
        level = "low"

    # Track consecutive high-load messages for proactive intervention
    key = str(user_id)
    if level == "high":
        _consecutive_high[key] = _consecutive_high.get(key, 0) + 1
    else:
        _consecutive_high[key] = 0
    consecutive = _consecutive_high.get(key, 0)

    # Generate teaching guidance
    guidance = _build_guidance(level, score, signals, consecutive)

    return {
        "score": round(score, 3),
        "level": level,
        "guidance": guidance,
        "signals": {k: round(v, 3) for k, v in signals.items()},
        "consecutive_high": consecutive,
        "affect": affect if user_message else {},
        "baseline_calibrated": relative.get("calibrated", False),
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
        # NLP-based signal advice
        if signals.get("nlp_affect", 0) > 0.5:
            parts.append(
                "- NLP analysis detects elevated frustration or confusion. "
                "Prioritize empathy and validation before instruction."
            )

    elif level == "medium":
        parts.append(
            "The student may be experiencing moderate cognitive load. Consider:\n"
            "- Slightly simpler explanations than default\n"
            "- Add a worked example alongside theory\n"
            "- Check understanding before adding complexity"
        )

    return "\n".join(parts)


# Priority order for hiding blocks under high cognitive load (least essential first)
_BLOCK_HIDE_PRIORITY = [
    "agent_insight",
    "forecast",
    "knowledge_graph",
    "podcast",
    "progress",
    "plan",
    "wrong_answers",
    "flashcards",
    "review",
    # "quiz", "notes", "chapter_list" — essential, never hidden
]


def suggest_layout_simplification(
    cognitive_load_score: float,
    current_block_types: list[str],
) -> dict:
    """Suggest which blocks to collapse/hide when cognitive load is high.

    Returns:
        {
            "should_simplify": bool,
            "blocks_to_hide": list of block type strings to collapse,
            "reason": str,
        }
    """
    if cognitive_load_score < 0.7:
        return {"should_simplify": False, "blocks_to_hide": [], "reason": ""}

    # Hide non-essential blocks, most dispensable first
    to_hide: list[str] = []
    for block_type in _BLOCK_HIDE_PRIORITY:
        if block_type in current_block_types:
            to_hide.append(block_type)
            # Hide enough to reduce visual clutter (max 3)
            if len(to_hide) >= 3:
                break

    if not to_hide:
        return {"should_simplify": False, "blocks_to_hide": [], "reason": ""}

    return {
        "should_simplify": True,
        "blocks_to_hide": to_hide,
        "reason": (
            f"Cognitive load is high ({cognitive_load_score:.0%}). "
            f"Consider hiding {', '.join(t.replace('_', ' ') for t in to_hide)} "
            "to reduce visual clutter and focus on core study."
        ),
    }


def adjust_review_order_for_load(
    cognitive_load_score: float,
    cards: list[dict],
) -> list[dict]:
    """Reorder review cards based on cognitive load — easier cards first when loaded.

    Under high cognitive load, presenting easier (more stable) cards first
    lets the student build confidence before tackling harder material.
    """
    if cognitive_load_score < 0.5 or not cards:
        return cards
    # Sort by FSRS stability descending (most stable = easiest recall)
    return sorted(
        cards,
        key=lambda c: c.get("fsrs", {}).get("stability", 0),
        reverse=True,
    )
