"""Auto-extracted teaching strategies — personalized pedagogical patterns.

Inspired by Claudeception's continuous learning system. Analyzes tutoring
conversations to extract effective teaching strategies, mistake patterns,
engagement techniques, and difficulty calibrations.

Stored in agent_kv with namespace="teaching_strategies".
Follows the same pattern as tutor_notes.py: kv_store, throttling, LLM extraction.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

STRATEGY_NAMESPACE = "teaching_strategies"
STRATEGY_KEY = "strategies"
STRATEGY_THROTTLE_KEY = "strategy_throttle"

# Throttle: extract every 10 turns or 20 minutes
STRATEGY_MIN_TURNS = 10
STRATEGY_MIN_SECONDS = 1200  # 20 minutes

# Maximum strategies to keep (older ones get pruned by confidence)
MAX_STRATEGIES = 20

STRATEGY_EXTRACTION_PROMPT = """Analyze this tutoring conversation turn. Extract teaching strategies that were effective or should be noted for future interactions with this student.

Strategy types to look for:
- effective_explanation: A metaphor, analogy, example, or approach that worked well
  Example: "Russian doll metaphor helped explain recursion"
- mistake_pattern: A recurring error or misconception the student shows
  Example: "Student confuses derivatives and integrals — needs explicit contrast"
- engagement_technique: An interaction style that increased student engagement
  Example: "Student responds better to examples-first, then theory"
- difficulty_calibration: Evidence about the student's comfort with different cognitive levels
  Example: "Student handles Bloom's Apply well but struggles with Analyze"

Rules:
- Extract 0-2 strategies per conversation turn (most turns yield 0)
- Only extract if there's clear evidence (don't invent patterns from a single instance)
- Be specific — mention the actual concept, topic, or technique
- Focus on what's reusable in future sessions
- If nothing notable, return exactly: NONE

Conversation:
Student: {user_message}
Tutor: {assistant_response}

Output NONE or a JSON array:
[{{"type": "<strategy_type>", "description": "<specific strategy>", "topic": "<related topic or concept>", "confidence": <0.0-1.0>}}]"""

VALID_STRATEGY_TYPES = frozenset({
    "effective_explanation",
    "mistake_pattern",
    "engagement_technique",
    "difficulty_calibration",
})


async def extract_teaching_strategies(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    user_message: str,
    assistant_response: str,
    intent: str | None = None,
) -> list[dict] | None:
    """Extract teaching strategies from a conversation turn.

    Only meaningful for LEARN, QUIZ, REVIEW intents. Uses fast LLM tier.
    """
    if intent and intent.lower() not in ("learn", "general", "plan"):
        return None

    from services.llm.router import get_llm_client

    client = get_llm_client("fast")

    try:
        result, _ = await client.extract(
            "You are a teaching methodology analyst. Output only valid JSON or NONE.",
            STRATEGY_EXTRACTION_PROMPT.format(
                user_message=user_message[:500],
                assistant_response=assistant_response[:800],
            ),
        )
        result = result.strip()

        if not result or result.upper().startswith("NONE"):
            return None

        # Handle markdown code blocks
        if "```" in result:
            json_start = result.find("[")
            json_end = result.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]

        strategies = json.loads(result)
        if not isinstance(strategies, list):
            return None

        valid = []
        for s in strategies[:2]:
            if not isinstance(s, dict) or "type" not in s or "description" not in s:
                continue
            if s["type"] not in VALID_STRATEGY_TYPES:
                continue
            desc = s["description"].strip()
            if not desc or len(desc) < 5:
                continue
            valid.append({
                "type": s["type"],
                "description": desc,
                "topic": s.get("topic", ""),
                "confidence": min(1.0, max(0.0, float(s.get("confidence", 0.5)))),
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            })

        return valid if valid else None

    except Exception as e:
        logger.exception("Teaching strategy extraction failed: %s", e)
        return None


async def get_teaching_strategies(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[dict]:
    """Retrieve stored teaching strategies from kv_store."""
    from services.agent.kv_store import kv_get

    try:
        value = await kv_get(
            db, user_id, STRATEGY_NAMESPACE, STRATEGY_KEY, course_id=course_id,
        )
        if isinstance(value, list):
            return value
        return []
    except Exception as e:
        logger.exception("Failed to load teaching strategies for user %s: %s", user_id, e)
        return []


async def save_teaching_strategies(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    new_strategies: list[dict],
) -> None:
    """Merge new strategies with existing ones, dedup, prune old ones."""
    from services.agent.kv_store import kv_set

    existing = await get_teaching_strategies(db, user_id, course_id)

    # Dedup by normalized description (strip whitespace + lowercase)
    existing_descs = {s["description"].strip().lower() for s in existing}
    for s in new_strategies:
        norm = s["description"].strip().lower()
        if norm not in existing_descs:
            existing.append(s)
            existing_descs.add(norm)

    # Sort by confidence descending, then recency; keep top MAX_STRATEGIES
    existing.sort(
        key=lambda s: (s.get("confidence", 0.5), s.get("extracted_at", "")),
        reverse=True,
    )
    existing = existing[:MAX_STRATEGIES]

    await kv_set(
        db, user_id, STRATEGY_NAMESPACE, STRATEGY_KEY,
        existing, course_id=course_id,
    )
    logger.info(
        "Teaching strategies updated for user %s course %s: %d total",
        user_id, course_id, len(existing),
    )


# ── Throttle helpers (same pattern as tutor_notes) ──

async def check_and_increment_strategy_turn(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> bool:
    """Increment turn counter and return True if strategy extraction is due."""
    from services.agent.kv_store import kv_get, kv_set

    meta = await kv_get(
        db, user_id, STRATEGY_NAMESPACE, STRATEGY_THROTTLE_KEY, course_id=course_id,
    )
    if not meta or not isinstance(meta, dict):
        # First turn — start counting, don't extract yet
        await kv_set(
            db, user_id, STRATEGY_NAMESPACE, STRATEGY_THROTTLE_KEY,
            {
                "turns_since_update": 0,
                "last_update_ts": datetime.now(timezone.utc).timestamp(),
            },
            course_id=course_id,
        )
        return False

    turns_since = meta.get("turns_since_update", 0)
    last_update_ts = meta.get("last_update_ts")
    should_extract = False

    if turns_since >= STRATEGY_MIN_TURNS:
        should_extract = True
    elif last_update_ts:
        elapsed = datetime.now(timezone.utc).timestamp() - last_update_ts
        if elapsed >= STRATEGY_MIN_SECONDS:
            should_extract = True

    meta["turns_since_update"] = turns_since + 1
    await kv_set(
        db, user_id, STRATEGY_NAMESPACE, STRATEGY_THROTTLE_KEY,
        meta, course_id=course_id,
    )
    return should_extract


async def reset_strategy_counter(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> None:
    """Reset the turn counter after a successful strategy extraction."""
    from services.agent.kv_store import kv_set

    meta = {
        "turns_since_update": 0,
        "last_update_ts": datetime.now(timezone.utc).timestamp(),
    }
    await kv_set(
        db, user_id, STRATEGY_NAMESPACE, STRATEGY_THROTTLE_KEY,
        meta, course_id=course_id,
    )
