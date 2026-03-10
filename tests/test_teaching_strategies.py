"""Tests for services.agent.teaching_strategies — pure-logic paths."""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from services.agent.teaching_strategies import (
    VALID_STRATEGY_TYPES,
    MAX_STRATEGIES,
    STRATEGY_MIN_TURNS,
    STRATEGY_MIN_SECONDS,
    extract_teaching_strategies,
    save_teaching_strategies,
    get_teaching_strategies,
    check_and_increment_strategy_turn,
    reset_strategy_counter,
)


# ── extract_teaching_strategies ──


@pytest.mark.asyncio
async def test_extract_skips_non_learning_intents():
    """Should return None for intents outside learn/general/plan."""
    db = AsyncMock()
    uid = uuid.uuid4()
    cid = uuid.uuid4()
    result = await extract_teaching_strategies(db, uid, cid, "hello", "hi", intent="quiz")
    assert result is None


@pytest.mark.asyncio
async def test_extract_returns_none_on_llm_none_response():
    """When the LLM returns 'NONE', no strategies should be extracted."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(return_value=("NONE", {}))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        result = await extract_teaching_strategies(
            db, uid, cid, "What is recursion?", "Recursion is a function that calls itself.",
            intent="learn",
        )
    assert result is None


@pytest.mark.asyncio
async def test_extract_parses_valid_json_strategies():
    """Should parse valid JSON strategies and filter by type."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    raw = json.dumps([
        {"type": "effective_explanation", "description": "Russian doll metaphor for recursion", "topic": "recursion", "confidence": 0.9},
        {"type": "bogus_type", "description": "This should be filtered out", "topic": "x", "confidence": 0.5},
    ])
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(return_value=(raw, {}))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        result = await extract_teaching_strategies(
            db, uid, cid, "user msg", "assistant msg", intent="learn",
        )

    assert result is not None
    assert len(result) == 1
    assert result[0]["type"] == "effective_explanation"
    assert result[0]["confidence"] == 0.9
    assert "extracted_at" in result[0]


@pytest.mark.asyncio
async def test_extract_handles_markdown_code_block():
    """Should extract JSON from markdown fenced code blocks."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    raw = '```json\n[{"type": "mistake_pattern", "description": "Confuses mean and median", "topic": "stats", "confidence": 0.7}]\n```'
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(return_value=(raw, {}))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        result = await extract_teaching_strategies(
            db, uid, cid, "user msg", "assistant msg", intent="general",
        )

    assert result is not None
    assert len(result) == 1
    assert result[0]["type"] == "mistake_pattern"


@pytest.mark.asyncio
async def test_extract_filters_short_descriptions():
    """Descriptions shorter than 5 chars should be rejected."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    raw = json.dumps([
        {"type": "effective_explanation", "description": "hi", "topic": "x", "confidence": 0.5},
    ])
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(return_value=(raw, {}))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        result = await extract_teaching_strategies(
            db, uid, cid, "msg", "resp", intent="learn",
        )
    assert result is None


@pytest.mark.asyncio
async def test_extract_clamps_confidence():
    """Confidence values outside 0-1 should be clamped."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    raw = json.dumps([
        {"type": "engagement_technique", "description": "Student prefers visual aids a lot", "topic": "visual", "confidence": 5.0},
    ])
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(return_value=(raw, {}))

    with patch("services.llm.router.get_llm_client", return_value=mock_client):
        result = await extract_teaching_strategies(
            db, uid, cid, "msg", "resp", intent="learn",
        )
    assert result is not None
    assert result[0]["confidence"] == 1.0


# ── save_teaching_strategies ──


@pytest.mark.asyncio
async def test_save_deduplicates_and_prunes():
    """Duplicate descriptions (case-insensitive) should be de-duplicated."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    existing = [
        {"description": "Use diagrams", "confidence": 0.8, "extracted_at": "2026-01-01T00:00:00+00:00"},
    ]

    new = [
        {"description": "use diagrams", "confidence": 0.9, "extracted_at": "2026-02-01T00:00:00+00:00"},
        {"description": "Try worked examples", "confidence": 0.7, "extracted_at": "2026-02-01T00:00:00+00:00"},
    ]

    with (
        patch("services.agent.kv_store.kv_get", new_callable=AsyncMock, return_value=existing),
        patch("services.agent.kv_store.kv_set", new_callable=AsyncMock) as mock_kv_set,
    ):
        await save_teaching_strategies(db, uid, cid, new)

    # kv_set should have been called with 2 items (original + new non-dup)
    saved = mock_kv_set.call_args[0][4]  # positional arg: value
    assert len(saved) == 2


# ── check_and_increment_strategy_turn ──


@pytest.mark.asyncio
async def test_throttle_first_turn_returns_false():
    """First turn should initialize counter and return False."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    with (
        patch("services.agent.kv_store.kv_get", new_callable=AsyncMock, return_value=None),
        patch("services.agent.kv_store.kv_set", new_callable=AsyncMock),
    ):
        result = await check_and_increment_strategy_turn(db, uid, cid)
    assert result is False


@pytest.mark.asyncio
async def test_throttle_returns_true_after_enough_turns():
    """Should return True when turns_since_update >= STRATEGY_MIN_TURNS."""
    db = AsyncMock()
    uid, cid = uuid.uuid4(), uuid.uuid4()

    meta = {"turns_since_update": STRATEGY_MIN_TURNS, "last_update_ts": datetime.now(timezone.utc).timestamp()}

    with (
        patch("services.agent.kv_store.kv_get", new_callable=AsyncMock, return_value=meta),
        patch("services.agent.kv_store.kv_set", new_callable=AsyncMock),
    ):
        result = await check_and_increment_strategy_turn(db, uid, cid)
    assert result is True
