"""Tests for services/agent/tool_tracking.py — tool call lifecycle tracking."""

import uuid
from unittest.mock import AsyncMock

import pytest

from services.agent.tool_tracking import (
    _OUTPUT_TRUNCATION,
    batch_record_tool_calls,
    get_tool_stats,
    record_tool_call,
)


def test_output_truncation_constant():
    """_OUTPUT_TRUNCATION is a reasonable limit."""
    assert isinstance(_OUTPUT_TRUNCATION, int)
    assert _OUTPUT_TRUNCATION > 0


@pytest.mark.asyncio
async def test_record_tool_call_success():
    """record_tool_call completes without error on valid input."""
    db = AsyncMock()
    await record_tool_call(
        db,
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        session_id="sess-123",
        agent_name="tutor_agent",
        tool_name="search_notes",
        input_json={"query": "test"},
        output_text="Found 3 results",
        status="success",
        duration_ms=42.5,
        iteration=1,
    )
    # No exception means success (function logs only, no DB write since Phase 1.3)


@pytest.mark.asyncio
async def test_record_tool_call_error_status():
    """record_tool_call handles error status."""
    db = AsyncMock()
    await record_tool_call(
        db,
        user_id=uuid.uuid4(),
        agent_name="exercise_agent",
        tool_name="generate_quiz",
        status="error",
        error_message="LLM timeout",
        duration_ms=5000.0,
    )


@pytest.mark.asyncio
async def test_batch_record_empty():
    """batch_record_tool_calls returns immediately for empty list."""
    db = AsyncMock()
    await batch_record_tool_calls(
        db,
        user_id=uuid.uuid4(),
        course_id=None,
        session_id=None,
        agent_name="tutor_agent",
        tool_calls=[],
    )


@pytest.mark.asyncio
async def test_batch_record_multiple_calls():
    """batch_record_tool_calls handles multiple tool calls."""
    db = AsyncMock()
    calls = [
        {"tool_name": "search", "input": {}, "output": "ok", "duration_ms": 10},
        {"tool_name": "generate", "input": {}, "output": "done", "duration_ms": 200},
    ]
    await batch_record_tool_calls(
        db,
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        session_id="sess-456",
        agent_name="tutor_agent",
        tool_calls=calls,
    )


@pytest.mark.asyncio
async def test_get_tool_stats_returns_empty():
    """get_tool_stats returns empty list (model removed in Phase 1.3)."""
    db = AsyncMock()
    result = await get_tool_stats(db, uuid.uuid4(), days=7)
    assert result == []
