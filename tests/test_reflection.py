"""Tests for services/agent/reflection.py — response quality self-check."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.reflection import (
    REFLECTION_PROMPT,
    IMPROVEMENT_PROMPT,
    reflect_and_improve,
)


def _make_ctx(response="This is a test response with enough length.", user_message="What is X?"):
    """Create a minimal AgentContext-like mock."""
    ctx = MagicMock()
    ctx.response = response
    ctx.user_message = user_message
    ctx.preferences = {"language": "en", "detail_level": "medium"}
    ctx.content_docs = [{"title": "Doc1", "content": "Some content here"}]
    ctx.metadata = {}
    ctx.delegated_agent = "tutor_agent"
    return ctx


def test_reflection_prompt_has_placeholders():
    """REFLECTION_PROMPT contains all required format placeholders."""
    assert "{user_message}" in REFLECTION_PROMPT
    assert "{preferences}" in REFLECTION_PROMPT
    assert "{response}" in REFLECTION_PROMPT
    assert "{context_summary}" in REFLECTION_PROMPT


def test_improvement_prompt_has_placeholders():
    """IMPROVEMENT_PROMPT contains all required format placeholders."""
    assert "{original_response}" in IMPROVEMENT_PROMPT
    assert "{issues}" in IMPROVEMENT_PROMPT
    assert "{suggestion}" in IMPROVEMENT_PROMPT
    assert "{user_message}" in IMPROVEMENT_PROMPT
    assert "{preferences}" in IMPROVEMENT_PROMPT


@pytest.mark.asyncio
async def test_reflect_skips_short_response():
    """Skips reflection when response is too short (< 20 chars)."""
    ctx = _make_ctx(response="Short")
    result = await reflect_and_improve(ctx)
    assert result is ctx
    assert "reflection" not in ctx.metadata


@pytest.mark.asyncio
async def test_reflect_skips_empty_response():
    """Skips reflection when response is empty."""
    ctx = _make_ctx(response="")
    result = await reflect_and_improve(ctx)
    assert result is ctx


@pytest.mark.asyncio
async def test_reflect_high_score_no_improvement():
    """High-scoring response (>=7) is kept unchanged."""
    ctx = _make_ctx()
    review_json = json.dumps({"score": 9, "issues": [], "suggestion": ""})

    mock_client = AsyncMock()
    mock_client.extract.return_value = (review_json, {})

    with patch("services.agent.reflection.get_llm_client", return_value=mock_client):
        result = await reflect_and_improve(ctx)

    assert result.metadata["reflection"]["score"] == 9
    assert result.metadata["reflection"]["improved"] is False
    assert result.response == "This is a test response with enough length."


@pytest.mark.asyncio
async def test_reflect_low_score_triggers_improvement():
    """Low-scoring response (<7) triggers improvement."""
    ctx = _make_ctx()
    review_json = json.dumps({
        "score": 4,
        "issues": ["Inaccurate claim about topic X"],
        "suggestion": "Correct the claim about X",
    })
    improved_response = "This is a much better and improved response."

    mock_client = AsyncMock()
    mock_client.extract.return_value = (review_json, {})
    mock_client.chat.return_value = (improved_response, {})

    with patch("services.agent.reflection.get_llm_client", return_value=mock_client):
        result = await reflect_and_improve(ctx)

    assert result.response == improved_response
    assert result.metadata["reflection"]["improved"] is True
    assert result.metadata["reflection"]["original_score"] == 4


@pytest.mark.asyncio
async def test_reflect_handles_llm_error_gracefully():
    """Reflection catches connection errors and stores error in metadata."""
    ctx = _make_ctx()

    mock_client = AsyncMock()
    mock_client.extract.side_effect = ConnectionError("LLM down")

    with patch("services.agent.reflection.get_llm_client", return_value=mock_client):
        result = await reflect_and_improve(ctx)

    assert "error" in result.metadata["reflection"]
    assert result.response == "This is a test response with enough length."
