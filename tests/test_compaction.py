"""Tests for token-aware session compaction (services/agent/compaction.py)."""

import pytest
from unittest.mock import AsyncMock, patch

from services.agent.compaction import (
    _estimate_tokens,
    get_context_window,
    estimate_session_tokens,
    emergency_trim,
    compact_session,
    prune_tool_schemas,
    DEFAULT_CONTEXT_WINDOW,
    KEEP_RECENT_MESSAGES,
    MODEL_CONTEXT_WINDOWS,
)


# ── Token estimation ──

def test_estimate_tokens_ascii():
    text = "hello world"  # 11 ASCII chars → ~2 tokens
    tokens = _estimate_tokens(text)
    assert tokens == 11 // 4  # 2


def test_estimate_tokens_cjk():
    text = "你好世界"  # 4 CJK chars → ~2 tokens
    tokens = _estimate_tokens(text)
    assert tokens == 4 // 2  # 2


def test_estimate_tokens_mixed():
    text = "hello 你好"  # 6 ASCII + 2 CJK
    tokens = _estimate_tokens(text)
    assert tokens == 6 // 4 + 2 // 2  # 1 + 1 = 2


def test_estimate_tokens_empty():
    assert _estimate_tokens("") == 0


# ── Context window lookup ──

def test_get_context_window_exact_match():
    assert get_context_window("gpt-4o") == 128_000


def test_get_context_window_case_insensitive():
    assert get_context_window("GPT-4O") == 128_000


def test_get_context_window_fuzzy_match():
    # "gpt-4o" is contained in "gpt-4o-2024-08-06"
    assert get_context_window("gpt-4o-2024-08-06") == 128_000


def test_get_context_window_anthropic():
    assert get_context_window("claude-sonnet-4") == 200_000


def test_get_context_window_unknown_model():
    assert get_context_window("some-unknown-model") == DEFAULT_CONTEXT_WINDOW


def test_get_context_window_empty():
    assert get_context_window("") == DEFAULT_CONTEXT_WINDOW


# ── Session token estimation ──

def test_estimate_session_tokens_basic():
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    tokens = estimate_session_tokens(messages)
    # Each message: content tokens + 4 overhead
    assert tokens > 0


def test_estimate_session_tokens_with_system_prompt():
    messages = [{"role": "user", "content": "test"}]
    tokens_no_sys = estimate_session_tokens(messages)
    tokens_with_sys = estimate_session_tokens(messages, system_prompt="You are a tutor." * 100)
    assert tokens_with_sys > tokens_no_sys


def test_estimate_session_tokens_with_tool_schemas():
    messages = [{"role": "user", "content": "test"}]
    tools = [
        {"function": {"name": "search_content", "description": "Search course content", "parameters": {"type": "object"}}},
    ]
    tokens_no_tools = estimate_session_tokens(messages)
    tokens_with_tools = estimate_session_tokens(messages, tool_schemas=tools)
    assert tokens_with_tools > tokens_no_tools


def test_estimate_session_tokens_multipart_content():
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "describe this image"}]},
    ]
    tokens = estimate_session_tokens(messages)
    assert tokens > 0


# ── Emergency trim ──

def _make_messages(n: int, content_size: int = 100) -> list[dict]:
    """Helper: create n messages with specified content size."""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "x" * content_size}
        for i in range(n)
    ]


def test_emergency_trim_few_messages_unchanged():
    """Fewer than KEEP_RECENT_MESSAGES → no trim."""
    msgs = _make_messages(3)
    result = emergency_trim(msgs, budget_tokens=100)
    assert len(result) == 3


def test_emergency_trim_keeps_recent():
    """Always keeps the last KEEP_RECENT_MESSAGES."""
    msgs = _make_messages(20, content_size=200)
    result = emergency_trim(msgs, budget_tokens=500)
    # Last KEEP_RECENT_MESSAGES should be preserved
    assert result[-KEEP_RECENT_MESSAGES:] == msgs[-KEEP_RECENT_MESSAGES:]


def test_emergency_trim_drops_oldest():
    """Under tight budget, older messages are dropped."""
    msgs = _make_messages(20, content_size=200)
    # Budget that can only hold recent messages
    result = emergency_trim(msgs, budget_tokens=400)
    assert len(result) < 20
    assert len(result) >= KEEP_RECENT_MESSAGES


def test_emergency_trim_extreme_budget():
    """Even recent messages exceed budget → keep only last 2."""
    msgs = _make_messages(10, content_size=5000)
    result = emergency_trim(msgs, budget_tokens=10)
    assert len(result) == 2
    assert result == msgs[-2:]


# ── Compact session ──

@pytest.mark.asyncio
async def test_compact_session_few_messages_noop():
    """Fewer than KEEP_RECENT_MESSAGES → returned as-is."""
    msgs = _make_messages(3)
    compacted, flushed = await compact_session(msgs, "gpt-4o-mini")
    assert compacted == msgs
    assert flushed == []


@pytest.mark.asyncio
async def test_compact_session_no_llm_fallback():
    """No LLM client → falls back to emergency_trim."""
    msgs = _make_messages(20, content_size=100)
    result, flushed = await compact_session(msgs, "gpt-4o-mini", llm_client=None)
    # Should have trimmed — result should be <= original
    assert len(result) <= len(msgs)
    # Recent messages preserved
    assert result[-KEEP_RECENT_MESSAGES:] == msgs[-KEEP_RECENT_MESSAGES:]
    assert flushed == []


@pytest.mark.asyncio
async def test_compact_session_with_llm():
    """LLM client available → produces summary + recent."""
    msgs = _make_messages(15, content_size=100)
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(
        side_effect=[
            ("[]", {}),
            ("Student discussed binary search.", {}),
        ]
    )

    result, flushed = await compact_session(msgs, "gpt-4o-mini", llm_client=mock_client)

    # Should be: 1 summary message + KEEP_RECENT_MESSAGES
    assert len(result) == KEEP_RECENT_MESSAGES + 1
    assert result[0]["role"] == "system"
    assert "summary" in result[0]["content"].lower()
    assert flushed == []
    assert mock_client.extract.await_count == 2


@pytest.mark.asyncio
async def test_compact_session_llm_failure_fallback():
    """LLM extraction fails → falls back to emergency_trim."""
    msgs = _make_messages(15, content_size=100)
    mock_client = AsyncMock()
    mock_client.extract = AsyncMock(side_effect=RuntimeError("LLM down"))

    result, flushed = await compact_session(msgs, "gpt-4o-mini", llm_client=mock_client)

    # Should still return something valid (emergency trim fallback)
    assert len(result) <= len(msgs)
    assert len(result) >= 2
    assert flushed == []


# ── Tool schema pruning ──

def _make_tool_schemas() -> list[dict]:
    return [
        {"function": {"name": "search_content", "description": "Search"}},
        {"function": {"name": "run_code", "description": "Execute code"}},
        {"function": {"name": "lookup_progress", "description": "Check progress"}},
        {"function": {"name": "get_mastery_report", "description": "Mastery report"}},
    ]


def test_prune_tool_schemas_no_filter():
    """No allowed set → return all tools."""
    tools = _make_tool_schemas()
    result = prune_tool_schemas(tools)
    assert len(result) == 4


def test_prune_tool_schemas_filter():
    """Filter to allowed tools only."""
    tools = _make_tool_schemas()
    result = prune_tool_schemas(tools, allowed_tool_names={"search_content", "lookup_progress"})
    assert len(result) == 2
    names = {t["function"]["name"] for t in result}
    assert names == {"search_content", "lookup_progress"}


def test_prune_tool_schemas_empty_set():
    """Empty allowed set → return all (no filtering)."""
    tools = _make_tool_schemas()
    result = prune_tool_schemas(tools, allowed_tool_names=set())
    assert len(result) == 4


def test_prune_tool_schemas_disjoint():
    """Allowed set has no overlap → empty result."""
    tools = _make_tool_schemas()
    result = prune_tool_schemas(tools, allowed_tool_names={"nonexistent_tool"})
    assert len(result) == 0
