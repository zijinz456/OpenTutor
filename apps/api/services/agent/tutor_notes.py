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
    except Exception as e:
        logger.warning("Failed to load tutor notes for user %s: %s", user_id, e)
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
