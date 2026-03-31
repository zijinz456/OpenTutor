"""Preference signal extractor — openakita Compiler pattern.

Borrows from:
- openakita Compiler: lightweight LLM call for extraction (not main conversation LLM)
- "No extraction by default" strategy: ~95% of conversations return NONE
- Dual-track: Main Brain handles conversation, Compiler extracts signals async

Phase 0-C: Simplified version with 5 preference dimensions.
Phase 1: Full 5-dimension extraction + batch processing.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

# Preference dimensions we extract signals for
DIMENSIONS = [
    "note_format",      # bullet_point | table | mind_map | step_by_step | summary
    "detail_level",     # concise | balanced | detailed
    "language",         # en | zh | auto
    "explanation_style", # formal | conversational | socratic | example_heavy
    "visual_preference", # auto | text_heavy | diagram_heavy | mixed
]

VALUE_NORMALIZATION = {
    "zh-cn": "zh",
    "zh-tw": "zh",
    "zh-hans": "zh",
    "zh-hant": "zh",
    "analogy": "example_heavy",
    "example_first": "example_heavy",
}

# Patterns that strongly indicate explicit preference expression
_EXPLICIT_PREFERENCE_PATTERNS = re.compile(
    r"\b(i prefer|i like|i love|please always|i find .{0,30} hard|i (don'?t|do not) like|"
    r"can you always|could you always|please use|please (don'?t|don't|do not) use)\b",
    re.IGNORECASE,
)

EXTRACTION_PROMPT = """You are a preference signal extractor for a learning platform.
Analyze the following conversation between a student and an AI tutor.
Extract any implicit or explicit preference signals about the student's learning style.

IMPORTANT: Most conversations contain NO preference signals. Only extract when there is clear evidence.
If no signal is found, return exactly: NONE

If you find a signal, return JSON (ONE signal per response):
{
  "signal_type": "explicit|modification|behavior|negative",
  "dimension": "<one of: note_format, detail_level, language, explanation_style, visual_preference>",
  "value": "<the preferred value>",
  "evidence": "<brief quote or description of evidence>"
}

Signal types:
- explicit: User directly states a preference ("I prefer bullet points")
- modification: User asks to change something ("Make it shorter", "Switch to table format")
- behavior: Inferred from behavior patterns (e.g., user always asks follow-up questions → prefers detailed)
- negative: User expresses dislike ("Too wordy", "Don't use diagrams")

Valid values for each dimension:
- note_format: bullet_point, table, mind_map, step_by_step, summary
- detail_level: concise, balanced, detailed
- language: en, zh, auto
- explanation_style: formal, conversational, socratic, example_heavy
- visual_preference: auto, text_heavy, diagram_heavy, mixed

Conversation:
"""


async def extract_preference_signal(
    user_message: str,
    assistant_response: str,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict | None:
    """Extract preference signal from a conversation turn.

    Uses the Compiler pattern (lightweight LLM call) to check if the
    conversation contains a preference signal.

    Returns signal dict or None if no signal detected.
    """
    client = get_llm_client("fast")

    conversation_text = f"Student: {user_message}\nTutor: {assistant_response}"

    # If the message contains explicit preference language, prepend a hint so
    # the LLM does not mistakenly return NONE.
    prompt = EXTRACTION_PROMPT
    if user_message and _EXPLICIT_PREFERENCE_PATTERNS.search(user_message):
        prompt = (
            EXTRACTION_PROMPT
            + "\nNOTE: The student message contains an explicit preference expression. "
            "You MUST extract a signal (do NOT return NONE).\n"
        )
        logger.debug("Explicit preference keyword detected in message: %s", user_message[:80])

    try:
        result, _ = await client.extract(prompt, conversation_text)
        result = result.strip()

        # "No extraction by default" — most responses should be NONE
        if result == "NONE" or not result or result.upper().startswith("NONE"):
            return None

        # Try to parse JSON from the response
        # Handle cases where LLM wraps JSON in markdown code blocks
        if "```" in result:
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]

        signal = json.loads(result)

        # Validate required fields
        if not all(k in signal for k in ("signal_type", "dimension", "value")):
            logger.warning(f"Incomplete signal: {signal}")
            return None

        # Validate dimension
        if signal["dimension"] not in DIMENSIONS:
            logger.warning(f"Unknown dimension: {signal['dimension']}")
            return None

        raw_value = str(signal["value"]).strip()
        normalized_value = VALUE_NORMALIZATION.get(raw_value.lower(), raw_value)

        return {
            "signal_type": signal["signal_type"],
            "dimension": signal["dimension"],
            "value": normalized_value,
            "context": {
                "evidence": signal.get("evidence", ""),
                "user_message": user_message[:200],
            },
            "user_id": user_id,
            "course_id": course_id,
        }

    except json.JSONDecodeError:
        logger.debug(f"No valid JSON in extraction result: {result[:100]}")
        return None
    except (ConnectionError, TimeoutError, RuntimeError) as e:
        logger.exception("Signal extraction failed")
        return None


# ---------------------------------------------------------------------------
# Behavior-based preference inference
# ---------------------------------------------------------------------------

def infer_time_of_day_preference(
    now: datetime | None = None,
) -> dict | None:
    """Infer detail_level preference based on time of day.

    Late-night learners (22:00–05:00) likely prefer concise content.
    Morning/afternoon learners are assumed to tolerate balanced detail.
    """
    now = now or datetime.now(timezone.utc)
    hour = now.hour
    if 22 <= hour or hour < 5:
        return {
            "signal_type": "behavior",
            "dimension": "detail_level",
            "value": "concise",
            "context": {"evidence": f"Late-night session (hour={hour})", "source": "time_of_day"},
        }
    return None


async def infer_from_quiz_performance(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    *,
    window: int = 20,
) -> list[dict]:
    """Infer preference signals from recent quiz performance.

    - Consistent high accuracy (>85%) → suggest increasing difficulty / detail.
    - Consistent low accuracy (<45%) → suggest reducing detail, more examples.
    """
    from sqlalchemy import select, desc
    from models.practice import PracticeResult, PracticeProblem

    stmt = (
        select(PracticeResult.is_correct)
        .join(PracticeProblem, PracticeResult.problem_id == PracticeProblem.id)
        .where(PracticeResult.user_id == user_id, PracticeProblem.course_id == course_id)
        .order_by(desc(PracticeResult.answered_at))
        .limit(window)
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if len(rows) < 10:
        return []

    accuracy = sum(1 for r in rows if r) / len(rows)
    signals: list[dict] = []

    if accuracy >= 0.85:
        signals.append({
            "signal_type": "behavior",
            "dimension": "detail_level",
            "value": "detailed",
            "context": {
                "evidence": f"High quiz accuracy ({accuracy:.0%} over {len(rows)} attempts)",
                "source": "quiz_performance",
            },
        })
    elif accuracy < 0.45:
        signals.append({
            "signal_type": "behavior",
            "dimension": "detail_level",
            "value": "concise",
            "context": {
                "evidence": f"Low quiz accuracy ({accuracy:.0%} over {len(rows)} attempts) — simpler explanations may help",
                "source": "quiz_performance",
            },
        })
        signals.append({
            "signal_type": "behavior",
            "dimension": "explanation_style",
            "value": "example_heavy",
            "context": {
                "evidence": f"Low quiz accuracy ({accuracy:.0%}) — more examples may reinforce understanding",
                "source": "quiz_performance",
            },
        })

    return signals


async def infer_from_interaction_patterns(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    *,
    window: int = 30,
) -> list[dict]:
    """Infer preferences from recent message length patterns.

    - If user consistently sends very short messages (<30 chars), they may
      prefer concise responses.
    - If user sends long detailed questions (>200 chars), they likely want
      detailed responses.
    """
    from sqlalchemy import select, desc, func
    from models.chat_message import ChatMessageLog
    from models.chat_session import ChatSession

    stmt = (
        select(func.length(ChatMessageLog.content))
        .join(ChatSession, ChatMessageLog.session_id == ChatSession.id)
        .where(
            ChatSession.user_id == user_id,
            ChatSession.course_id == course_id,
            ChatMessageLog.role == "user",
        )
        .order_by(desc(ChatMessageLog.created_at))
        .limit(window)
    )
    result = await db.execute(stmt)
    lengths = result.scalars().all()

    if len(lengths) < 10:
        return []

    avg_length = sum(lengths) / len(lengths)
    signals: list[dict] = []

    if avg_length < 30:
        signals.append({
            "signal_type": "behavior",
            "dimension": "detail_level",
            "value": "concise",
            "context": {
                "evidence": f"Average message length {avg_length:.0f} chars — user prefers brevity",
                "source": "interaction_pattern",
            },
        })
    elif avg_length > 200:
        signals.append({
            "signal_type": "behavior",
            "dimension": "detail_level",
            "value": "detailed",
            "context": {
                "evidence": f"Average message length {avg_length:.0f} chars — user engages deeply",
                "source": "interaction_pattern",
            },
        })

    return signals


async def collect_behavior_signals(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[dict]:
    """Aggregate all behavior-based preference signals.

    Called periodically (e.g., after every N interactions) to supplement
    the primary LLM-based extraction.
    """
    signals: list[dict] = []

    # Time-of-day signal
    tod_signal = infer_time_of_day_preference()
    if tod_signal:
        tod_signal["user_id"] = user_id
        tod_signal["course_id"] = course_id
        signals.append(tod_signal)

    # Quiz performance signals
    try:
        quiz_signals = await infer_from_quiz_performance(db, user_id, course_id)
        for s in quiz_signals:
            s["user_id"] = user_id
            s["course_id"] = course_id
        signals.extend(quiz_signals)
    except (ValueError, RuntimeError, OSError, ImportError) as e:
        logger.debug("Quiz performance inference skipped: %s", e)

    # Interaction pattern signals
    try:
        pattern_signals = await infer_from_interaction_patterns(db, user_id, course_id)
        for s in pattern_signals:
            s["user_id"] = user_id
            s["course_id"] = course_id
        signals.extend(pattern_signals)
    except (ValueError, RuntimeError, OSError, ImportError) as e:
        logger.debug("Interaction pattern inference skipped: %s", e)

    return signals
