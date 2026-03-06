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
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


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
    load += fatigue_score * 0.25  # Max contribution: 0.25

    # ── Signal 2: Session length fatigue ──
    # Cognitive performance degrades after ~45 min of focused study
    session_fatigue = min(session_messages / 40.0, 1.0)  # ~40 messages ≈ 45 min
    signals["session_length"] = session_fatigue
    load += session_fatigue * 0.15  # Max contribution: 0.15

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
        load += error_signal * 0.20  # Max contribution: 0.20
    except Exception:
        signals["unmastered_errors"] = 0.0

    # ── Signal 4: Message complexity drop ──
    # Short, terse messages may indicate frustration or overload
    msg_len = len(user_message.strip())
    if msg_len > 0:
        brevity_signal = max(0.0, 1.0 - (msg_len / 100.0))  # <100 chars = some signal
        # Only count if we have session context (student was writing longer before)
        if session_messages > 3:
            signals["message_brevity"] = brevity_signal
            load += brevity_signal * 0.10  # Max contribution: 0.10
        else:
            signals["message_brevity"] = 0.0
    else:
        signals["message_brevity"] = 0.0

    # ── Signal 5: Help-seeking indicators ──
    # Detect explicit help-seeking in current message
    help_keywords = ["help", "hint", "explain", "don't understand", "confused", "stuck", "how do i"]
    help_signal = 1.0 if any(kw in user_message.lower() for kw in help_keywords) else 0.0
    signals["help_seeking"] = help_signal
    load += help_signal * 0.15  # Max contribution: 0.15

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
            load += perf_signal * 0.15  # Max contribution: 0.15
        else:
            signals["quiz_performance"] = 0.0
    except Exception:
        signals["quiz_performance"] = 0.0

    # Clamp
    score = max(0.0, min(load, 1.0))

    # Determine level
    if score > 0.6:
        level = "high"
    elif score > 0.3:
        level = "medium"
    else:
        level = "low"

    # Generate teaching guidance
    guidance = _build_guidance(level, score, signals)

    return {
        "score": round(score, 3),
        "level": level,
        "guidance": guidance,
        "signals": {k: round(v, 3) for k, v in signals.items()},
    }


def _build_guidance(level: str, score: float, signals: dict) -> str:
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

    elif level == "medium":
        parts.append(
            "The student may be experiencing moderate cognitive load. Consider:\n"
            "- Slightly simpler explanations than default\n"
            "- Add a worked example alongside theory\n"
            "- Check understanding before adding complexity"
        )

    return "\n".join(parts)
