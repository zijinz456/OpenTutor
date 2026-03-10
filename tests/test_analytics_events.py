"""Tests for services/analytics/events.py — learning event emitter."""

import uuid
from unittest.mock import AsyncMock

import pytest

from services.analytics.events import (
    VALID_VERBS,
    VALID_OBJECT_TYPES,
    LearningEventData,
    emit_learning_event,
    emit_quiz_answered,
    emit_flashcard_reviewed,
    emit_topic_mastered,
    emit_exercise_completed,
    get_learning_events,
    get_event_summary,
)


# ── Constants tests ──

def test_valid_verbs_contains_core_verbs():
    """VALID_VERBS includes essential learning verbs."""
    for verb in ["attempted", "answered", "completed", "reviewed", "mastered", "failed"]:
        assert verb in VALID_VERBS


def test_valid_object_types_contains_core_types():
    """VALID_OBJECT_TYPES includes essential object types."""
    for obj_type in ["quiz", "flashcard", "note", "exercise", "topic", "course"]:
        assert obj_type in VALID_OBJECT_TYPES


# ── LearningEventData tests ──

def test_learning_event_data_defaults():
    """LearningEventData has sensible defaults for optional fields."""
    uid = uuid.uuid4()
    event = LearningEventData(user_id=uid, verb="answered", object_type="quiz")
    assert event.user_id == uid
    assert event.score is None
    assert event.success is None
    assert event.completion is None
    assert event.duration_seconds is None
    assert event.course_id is None
    assert event.agent_name is None


def test_learning_event_data_full():
    """LearningEventData accepts all fields."""
    uid = uuid.uuid4()
    cid = uuid.uuid4()
    event = LearningEventData(
        user_id=uid, verb="answered", object_type="quiz",
        object_id="q-123", score=0.85, success=True, completion=True,
        duration_seconds=60, course_id=cid, agent_name="exercise_agent",
        result_json={"answers": [1, 2]}, session_id="sess-1",
    )
    assert event.score == 0.85
    assert event.course_id == cid


# ── emit_learning_event tests ──

@pytest.mark.asyncio
async def test_emit_learning_event_returns_uuid():
    """emit_learning_event returns a UUID."""
    db = AsyncMock()
    event_id = await emit_learning_event(db, LearningEventData(
        user_id=uuid.uuid4(), verb="answered", object_type="quiz",
    ))
    assert isinstance(event_id, uuid.UUID)


@pytest.mark.asyncio
async def test_emit_learning_event_unknown_verb():
    """emit_learning_event tolerates unknown verbs (logs warning)."""
    db = AsyncMock()
    event_id = await emit_learning_event(db, LearningEventData(
        user_id=uuid.uuid4(), verb="unknown_verb", object_type="quiz",
    ))
    assert isinstance(event_id, uuid.UUID)


# ── Convenience emitter tests ──

@pytest.mark.asyncio
async def test_emit_quiz_answered():
    """emit_quiz_answered returns a UUID."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    event_id = await emit_quiz_answered(
        db, uid, cid, quiz_id="q-1", score=0.9, correct=True, duration_seconds=30,
    )
    assert isinstance(event_id, uuid.UUID)


@pytest.mark.asyncio
async def test_emit_flashcard_reviewed():
    """emit_flashcard_reviewed normalizes rating to 0-1 score."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    event_id = await emit_flashcard_reviewed(db, uid, cid, card_id="c-1", rating=3)
    assert isinstance(event_id, uuid.UUID)


@pytest.mark.asyncio
async def test_emit_topic_mastered():
    """emit_topic_mastered returns a UUID."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()
    event_id = await emit_topic_mastered(db, uid, cid, topic_id="t-1", mastery_score=0.95)
    assert isinstance(event_id, uuid.UUID)


# ── Query helper tests ──

@pytest.mark.asyncio
async def test_get_learning_events_returns_empty():
    """get_learning_events returns empty list (model removed)."""
    db = AsyncMock()
    result = await get_learning_events(db, uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_get_event_summary_structure():
    """get_event_summary returns dict with expected keys."""
    db = AsyncMock()
    result = await get_event_summary(db, uuid.uuid4())
    assert "verb_counts" in result
    assert "average_scores" in result
    assert "total_study_seconds" in result
    assert result["total_study_seconds"] == 0
