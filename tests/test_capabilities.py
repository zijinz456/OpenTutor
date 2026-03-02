"""Tests for agent capability declarations and permission enforcement."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from services.agent.capabilities import (
    AGENT_CAPABILITIES,
    check_tool_permission,
    get_allowed_tools,
    check_delegation_escalation,
)
from services.agent.tools.base import ToolRegistry, ToolResult


# ── check_tool_permission ──


def test_teaching_can_search_content():
    assert check_tool_permission("teaching", "search_content") is True


def test_teaching_can_lookup_progress():
    assert check_tool_permission("teaching", "lookup_progress") is True


def test_teaching_cannot_run_code():
    assert check_tool_permission("teaching", "run_code") is False


def test_preference_has_no_tools():
    assert check_tool_permission("preference", "search_content") is False
    assert check_tool_permission("preference", "run_code") is False


def test_scene_has_no_tools():
    assert check_tool_permission("scene", "lookup_progress") is False


def test_motivation_has_no_tools():
    assert check_tool_permission("motivation", "search_content") is False


def test_code_execution_can_run_code():
    assert check_tool_permission("code_execution", "run_code") is True


def test_code_execution_cannot_list_wrong_answers():
    assert check_tool_permission("code_execution", "list_wrong_answers") is False


def test_exercise_can_list_wrong_answers():
    assert check_tool_permission("exercise", "list_wrong_answers") is True


def test_planning_can_list_assignments():
    assert check_tool_permission("planning", "list_assignments") is True


def test_planning_cannot_run_code():
    assert check_tool_permission("planning", "run_code") is False


def test_unknown_agent_is_allowed():
    """Unknown agents bypass checks (backward compat for plugins)."""
    assert check_tool_permission("custom_plugin_agent", "anything") is True


# ── get_allowed_tools ──


def test_get_allowed_tools_teaching():
    tools = get_allowed_tools("teaching")
    assert tools == {"search_content", "lookup_progress", "get_course_outline"}


def test_get_allowed_tools_preference_empty():
    tools = get_allowed_tools("preference")
    assert tools == set()


def test_get_allowed_tools_unknown_returns_none():
    assert get_allowed_tools("nonexistent_agent") is None


# ── check_delegation_escalation ──


def test_delegation_teaching_to_review_allowed():
    """Teaching has {search_content, lookup_progress, get_course_outline}.
    Review has {list_wrong_answers, search_content, lookup_progress}.
    Review has list_wrong_answers which teaching lacks → blocked."""
    allowed, reason = check_delegation_escalation("teaching", "review")
    assert allowed is False
    assert "list_wrong_answers" in reason


def test_delegation_exercise_to_review_allowed():
    """Exercise has {search_content, lookup_progress, get_mastery_report, list_wrong_answers}.
    Review has {list_wrong_answers, search_content, lookup_progress}.
    Review is a subset → allowed."""
    allowed, reason = check_delegation_escalation("exercise", "review")
    assert allowed is True


def test_delegation_preference_to_code_execution_blocked():
    """Preference has no tools. Code execution has {run_code, search_content}.
    Massive escalation → blocked."""
    allowed, reason = check_delegation_escalation("preference", "code_execution")
    assert allowed is False
    assert "run_code" in reason


def test_delegation_teaching_to_preference_allowed():
    """Preference has no tools — delegating to a less-capable agent is fine."""
    allowed, reason = check_delegation_escalation("teaching", "preference")
    assert allowed is True


def test_delegation_unknown_agent_allowed():
    """Unknown source or target → allowed (backward compat)."""
    allowed, _ = check_delegation_escalation("unknown_agent", "teaching")
    assert allowed is True
    allowed, _ = check_delegation_escalation("teaching", "unknown_agent")
    assert allowed is True


def test_delegation_same_agent_allowed():
    """Self-delegation is always allowed."""
    allowed, _ = check_delegation_escalation("teaching", "teaching")
    assert allowed is True


# ── ToolRegistry.execute() with agent_name ──


@pytest.mark.asyncio
async def test_registry_execute_with_capability_check():
    """ToolRegistry.execute() blocks tools when agent lacks permission."""
    registry = ToolRegistry()

    # Create a mock tool
    mock_tool = MagicMock()
    mock_tool.name = "run_code"
    mock_tool.domain = "education"
    mock_tool.run = AsyncMock(return_value=ToolResult(success=True, output="hello"))
    registry.register(mock_tool)

    # Teaching agent tries to use run_code → should be blocked
    result = await registry.execute(
        "run_code", {"code": "print('hi')"}, ctx=MagicMock(), db=MagicMock(),
        agent_name="teaching",
    )
    assert result.success is False
    assert "not allowed" in result.error
    mock_tool.run.assert_not_called()


@pytest.mark.asyncio
async def test_registry_execute_allowed_tool():
    """ToolRegistry.execute() allows tools when agent has permission."""
    registry = ToolRegistry()

    mock_tool = MagicMock()
    mock_tool.name = "search_content"
    mock_tool.domain = "education"
    mock_tool.run = AsyncMock(return_value=ToolResult(success=True, output="found it"))
    registry.register(mock_tool)

    result = await registry.execute(
        "search_content", {"query": "test"}, ctx=MagicMock(), db=MagicMock(),
        agent_name="teaching",
    )
    assert result.success is True
    assert result.output == "found it"
    mock_tool.run.assert_called_once()


@pytest.mark.asyncio
async def test_registry_execute_no_agent_name_skips_check():
    """agent_name=None → no capability check (backward compat)."""
    registry = ToolRegistry()

    mock_tool = MagicMock()
    mock_tool.name = "run_code"
    mock_tool.domain = "education"
    mock_tool.run = AsyncMock(return_value=ToolResult(success=True, output="42"))
    registry.register(mock_tool)

    # No agent_name → should execute without restriction
    result = await registry.execute(
        "run_code", {"code": "1+1"}, ctx=MagicMock(), db=MagicMock(),
    )
    assert result.success is True
    mock_tool.run.assert_called_once()


# ── All declared agents have valid tool names ──


def test_all_capability_tools_exist_in_builtin():
    """Every tool in AGENT_CAPABILITIES should be a real builtin tool name."""
    from services.agent.tools.education import get_builtin_tools

    builtin_names = {t.name for t in get_builtin_tools()}

    for agent, tools in AGENT_CAPABILITIES.items():
        for tool_name in tools:
            assert tool_name in builtin_names, (
                f"Agent '{agent}' declares tool '{tool_name}' which is not a builtin tool. "
                f"Available: {builtin_names}"
            )
