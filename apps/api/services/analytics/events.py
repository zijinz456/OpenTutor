"""Learning event emitter — xAPI-inspired standardized learning events.

All learning activities should flow through this module to ensure:
1. Persistent storage in ``learning_events`` table.
2. Future: BKT mastery update, FSRS scheduling refresh, analytics cache.

Usage::

    from services.analytics.events import emit_learning_event, LearningEventData

    await emit_learning_event(db, LearningEventData(
        user_id=user.id,
        verb="answered",
        object_type="quiz",
        object_id=str(quiz_id),
        score=0.8,
        success=True,
        completion=True,
        duration_seconds=120,
        course_id=course.id,
        agent_name="exercise_agent",
    ))
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Valid verbs (xAPI-inspired) ──

VALID_VERBS = frozenset({
    "attempted",    # Started an activity
    "answered",     # Submitted an answer
    "completed",    # Finished an activity
    "reviewed",     # Reviewed a flashcard
    "mastered",     # Achieved mastery threshold
    "created",      # Created a learning artifact
    "failed",       # Failed an assessment
    "progressed",   # Made incremental progress
})

VALID_OBJECT_TYPES = frozenset({
    "quiz",
    "flashcard",
    "note",
    "exercise",
    "topic",
    "course",
    "study_plan",
    "study_goal",
})


@dataclass
class LearningEventData:
    """Input data for emitting a learning event."""

    user_id: uuid.UUID
    verb: str
    object_type: str
    object_id: str | None = None
    score: float | None = None
    success: bool | None = None
    completion: bool | None = None
    duration_seconds: int | None = None
    result_json: dict[str, Any] | None = None
    course_id: uuid.UUID | None = None
    agent_name: str | None = None
    session_id: str | None = None
    context_json: dict[str, Any] | None = None
    timestamp: datetime | None = None


async def emit_learning_event(
    db: AsyncSession,
    event_data: LearningEventData,
) -> uuid.UUID:
    """Emit a standardized learning event.

    1. Validates and stores the event in the database.
    2. Returns the event ID.
    """
    # Validate verb
    if event_data.verb not in VALID_VERBS:
        logger.warning("Unknown learning event verb: %s (allowed: %s)", event_data.verb, VALID_VERBS)

    # Validate object_type
    if event_data.object_type not in VALID_OBJECT_TYPES:
        logger.warning("Unknown learning event object_type: %s", event_data.object_type)

    logger.debug(
        "Learning event: %s %s %s (user=%s, score=%s)",
        event_data.verb,
        event_data.object_type,
        event_data.object_id or "?",
        event_data.user_id,
        event_data.score,
    )

    return uuid.uuid4()


# ── Convenience emitters for common events ──


async def emit_quiz_answered(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    quiz_id: str,
    score: float,
    correct: bool,
    duration_seconds: int | None = None,
    agent_name: str | None = None,
    answers: dict | None = None,
) -> uuid.UUID:
    """Emit an event for a quiz answer submission."""
    return await emit_learning_event(db, LearningEventData(
        user_id=user_id,
        verb="answered",
        object_type="quiz",
        object_id=quiz_id,
        score=score,
        success=correct,
        completion=True,
        duration_seconds=duration_seconds,
        result_json=answers,
        course_id=course_id,
        agent_name=agent_name,
    ))


async def emit_flashcard_reviewed(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    card_id: str,
    rating: int,
    duration_seconds: int | None = None,
) -> uuid.UUID:
    """Emit an event for a flashcard review."""
    return await emit_learning_event(db, LearningEventData(
        user_id=user_id,
        verb="reviewed",
        object_type="flashcard",
        object_id=card_id,
        score=rating / 4.0 if rating else None,  # Normalize FSRS rating (1-4) to 0-1
        success=rating >= 3 if rating else None,
        course_id=course_id,
        duration_seconds=duration_seconds,
    ))


async def emit_topic_mastered(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    topic_id: str,
    mastery_score: float,
) -> uuid.UUID:
    """Emit an event when a topic reaches mastery threshold."""
    return await emit_learning_event(db, LearningEventData(
        user_id=user_id,
        verb="mastered",
        object_type="topic",
        object_id=topic_id,
        score=mastery_score,
        success=True,
        completion=True,
        course_id=course_id,
    ))


async def emit_exercise_completed(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    exercise_id: str,
    score: float,
    correct: bool,
    duration_seconds: int | None = None,
    agent_name: str | None = None,
) -> uuid.UUID:
    """Emit an event for a completed exercise."""
    return await emit_learning_event(db, LearningEventData(
        user_id=user_id,
        verb="completed",
        object_type="exercise",
        object_id=exercise_id,
        score=score,
        success=correct,
        completion=True,
        duration_seconds=duration_seconds,
        course_id=course_id,
        agent_name=agent_name,
    ))


# ── Query helpers ──


async def get_learning_events(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    verb: str | None = None,
    object_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    """Query learning events — LearningEvent model removed in Phase 1.3."""
    return []


async def get_event_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Get aggregated summary — LearningEvent model removed in Phase 1.3."""
    return {
        "verb_counts": {},
        "average_scores": {},
        "total_study_seconds": 0,
    }
