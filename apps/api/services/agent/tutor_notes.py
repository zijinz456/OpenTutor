"""Self-evolving tutor notes — private observations about each student.

The tutor agent maintains per-student, per-course notes that evolve over time.
Notes capture learning style, strengths, struggles, misconceptions, pace,
and emotional state. Stored in agent_kv with namespace="tutor_notes".
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

TUTOR_NOTES_NAMESPACE = "tutor_notes"
TUTOR_NOTES_KEY = "notes"
TUTOR_NOTES_THROTTLE_KEY = "throttle_meta"

# Phase 4: Throttle tutor notes updates to reduce LLM cost
TUTOR_NOTES_MIN_TURNS = 5       # Update after at least 5 turns
TUTOR_NOTES_MIN_SECONDS = 600   # Or 10 minutes of wall time

UPDATE_SYSTEM_PROMPT = (
    "You maintain private tutor notes about a student. "
    "Update these notes with new observations from the latest session. "
    "Keep notes concise (under 500 words). "
    "Focus on: learning style, strengths, struggles, misconceptions, pace, emotional state. "
    "Output only the updated notes."
)


async def get_tutor_notes(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> str | None:
    """Read tutor notes from agent_kv. Returns the notes string or None."""
    from services.agent.kv_store import kv_get

    try:
        value = await kv_get(
            db, user_id, TUTOR_NOTES_NAMESPACE, TUTOR_NOTES_KEY,
            course_id=course_id,
        )
        if isinstance(value, str):
            return value
        return None
    except (ConnectionError, TimeoutError, KeyError, ValueError) as e:
        logger.exception("Failed to load tutor notes for user %s: %s", user_id, e)
        return None


async def update_tutor_notes(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    current_notes: str | None,
    conversation_summary: str,
) -> str:
    """Use LLM (fast tier) to evolve tutor notes, then persist via kv_set.

    Args:
        db: async DB session
        user_id: student user ID
        course_id: course ID
        current_notes: existing notes (may be None for first session)
        conversation_summary: brief summary of the latest conversation

    Returns:
        The updated notes string.
    """
    from services.llm.router import get_llm_client
    from services.agent.kv_store import kv_set

    existing = current_notes or "(No previous notes — this is the first session with this student.)"

    user_message = (
        f"## Current Notes\n{existing}\n\n"
        f"## Latest Session Summary\n{conversation_summary}"
    )

    client = get_llm_client("fast")
    updated_notes, _ = await client.extract(UPDATE_SYSTEM_PROMPT, user_message)
    updated_notes = updated_notes.strip()

    # Sanity: if LLM returned empty or obviously broken output, keep old notes
    if not updated_notes or len(updated_notes) < 10:
        logger.warning("LLM returned unusable tutor notes update; keeping existing notes.")
        updated_notes = current_notes or ""

    await kv_set(
        db, user_id, TUTOR_NOTES_NAMESPACE, TUTOR_NOTES_KEY,
        updated_notes, course_id=course_id,
    )

    logger.info("Tutor notes updated for user %s, course %s (%d chars)", user_id, course_id, len(updated_notes))
    return updated_notes


# ── Phase 4: Throttle helpers ──

async def check_and_increment_turn(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> bool:
    """Increment turn counter and return True if a notes update is due.

    Combines check + increment into a single read/write to avoid redundant
    kv_get calls. Triggers update when either:
    - At least TUTOR_NOTES_MIN_TURNS turns have elapsed since last update, OR
    - At least TUTOR_NOTES_MIN_SECONDS seconds have elapsed since last update
    """
    from services.agent.kv_store import kv_get, kv_set
    from datetime import datetime, timezone

    meta = await kv_get(db, user_id, TUTOR_NOTES_NAMESPACE, TUTOR_NOTES_THROTTLE_KEY, course_id=course_id)
    if not meta or not isinstance(meta, dict):
        # First time — increment to 1 and trigger update
        await kv_set(
            db, user_id, TUTOR_NOTES_NAMESPACE, TUTOR_NOTES_THROTTLE_KEY,
            {"turns_since_update": 1}, course_id=course_id,
        )
        return True

    # Check thresholds BEFORE incrementing
    turns_since = meta.get("turns_since_update", 0)
    last_update_ts = meta.get("last_update_ts")
    should_update = False

    if turns_since >= TUTOR_NOTES_MIN_TURNS:
        should_update = True
    elif last_update_ts:
        elapsed = datetime.now(timezone.utc).timestamp() - last_update_ts
        if elapsed >= TUTOR_NOTES_MIN_SECONDS:
            should_update = True

    # Increment counter (will be reset if update succeeds)
    meta["turns_since_update"] = turns_since + 1
    await kv_set(
        db, user_id, TUTOR_NOTES_NAMESPACE, TUTOR_NOTES_THROTTLE_KEY,
        meta, course_id=course_id,
    )
    return should_update


async def reset_turn_counter(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> None:
    """Reset the turn counter after a successful notes update."""
    from services.agent.kv_store import kv_set
    from datetime import datetime, timezone

    meta = {
        "turns_since_update": 0,
        "last_update_ts": datetime.now(timezone.utc).timestamp(),
    }
    await kv_set(db, user_id, TUTOR_NOTES_NAMESPACE, TUTOR_NOTES_THROTTLE_KEY, meta, course_id=course_id)
