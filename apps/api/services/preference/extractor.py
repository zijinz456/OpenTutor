"""Preference signal extractor — openakita Compiler pattern.

Borrows from:
- openakita Compiler: lightweight LLM call for extraction (not main conversation LLM)
- "默认不提取" strategy: ~95% of conversations return NONE
- Dual-track: Main Brain handles conversation, Compiler extracts signals async

Phase 0-C: Simplified version with 5 preference dimensions.
Phase 1: Full 5-dimension extraction + batch processing.
"""

import json
import logging
import uuid

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
    client = get_llm_client()

    conversation_text = f"Student: {user_message}\nTutor: {assistant_response}"

    try:
        result = await client.extract(EXTRACTION_PROMPT, conversation_text)
        result = result.strip()

        # "默认不提取" — most responses should be NONE
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

        return {
            "signal_type": signal["signal_type"],
            "dimension": signal["dimension"],
            "value": signal["value"],
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
    except Exception as e:
        logger.warning(f"Signal extraction failed: {e}")
        return None
