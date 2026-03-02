"""Learning event emitter — xAPI-inspired standardized learning events.

All learning activities should flow through this module to ensure:
1. Persistent storage in ``learning_events`` table.
2. Pluggy hook dispatch (``on_learning_event``) for plugin reactions.
3. Future: BKT mastery update, FSRS scheduling refresh, analytics cache.

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
    2. Dispatches to pluggy ``on_learning_event`` hooks.
    3. Returns the event ID.
    """
    from models.learning_event import LearningEvent

    # Validate verb
    if event_data.verb not in VALID_VERBS:
        logger.warning("Unknown learning event verb: %s (allowed: %s)", event_data.verb, VALID_VERBS)

    # Validate object_type
    if event_data.object_type not in VALID_OBJECT_TYPES:
        logger.warning("Unknown learning event object_type: %s", event_data.object_type)

    # Create event record
    event = LearningEvent(
        user_id=event_data.user_id,
        verb=event_data.verb,
        object_type=event_data.object_type,
        object_id=event_data.object_id,
        score=event_data.score,
        success=event_data.success,
        completion=event_data.completion,
        duration_seconds=event_data.duration_seconds,
        result_json=event_data.result_json,
        course_id=event_data.course_id,
        agent_name=event_data.agent_name,
        session_id=event_data.session_id,
        context_json=event_data.context_json,
        timestamp=event_data.timestamp or datetime.now(timezone.utc),
    )

    db.add(event)
    await db.flush()

    logger.debug(
        "Learning event: %s %s %s (user=%s, score=%s)",
        event_data.verb,
        event_data.object_type,
        event_data.object_id or "?",
        event_data.user_id,
        event_data.score,
    )

    # Dispatch to pluggy hooks (non-blocking, errors logged)
    _dispatch_plugin_hooks(event_data)

    return event.id


def _dispatch_plugin_hooks(event_data: LearningEventData) -> None:
    """Fire on_learning_event hooks for all registered plugins."""
    try:
        from services.plugin.manager import get_plugin_manager

        pm = get_plugin_manager()
        pm.hook.on_learning_event(event=event_data)
    except Exception as e:
        logger.debug("Plugin learning event dispatch failed: %s", e)


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
        score=rating / 5.0 if rating else None,  # Normalize FSRS rating (1-5) to 0-1
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
    """Query learning events with optional filters."""
    from sqlalchemy import select
    from models.learning_event import LearningEvent

    stmt = (
        select(LearningEvent)
        .where(LearningEvent.user_id == user_id)
        .order_by(LearningEvent.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )

    if course_id:
        stmt = stmt.where(LearningEvent.course_id == course_id)
    if verb:
        stmt = stmt.where(LearningEvent.verb == verb)
    if object_type:
        stmt = stmt.where(LearningEvent.object_type == object_type)

    result = await db.execute(stmt)
    return result.scalars().all()


async def get_event_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Get aggregated summary of learning events."""
    from sqlalchemy import func, select
    from models.learning_event import LearningEvent

    base_filter = [LearningEvent.user_id == user_id]
    if course_id:
        base_filter.append(LearningEvent.course_id == course_id)

    # Count by verb
    verb_counts = await db.execute(
        select(LearningEvent.verb, func.count(LearningEvent.id))
        .where(*base_filter)
        .group_by(LearningEvent.verb)
    )

    # Average scores by object type
    avg_scores = await db.execute(
        select(
            LearningEvent.object_type,
            func.avg(LearningEvent.score),
            func.count(LearningEvent.id),
        )
        .where(*base_filter, LearningEvent.score.isnot(None))
        .group_by(LearningEvent.object_type)
    )

    # Total study time
    total_time = await db.execute(
        select(func.sum(LearningEvent.duration_seconds))
        .where(*base_filter, LearningEvent.duration_seconds.isnot(None))
    )

    return {
        "verb_counts": {row[0]: row[1] for row in verb_counts.all()},
        "average_scores": {
            row[0]: {"avg_score": round(row[1], 3), "count": row[2]}
            for row in avg_scores.all()
        },
        "total_study_seconds": total_time.scalar() or 0,
    }
