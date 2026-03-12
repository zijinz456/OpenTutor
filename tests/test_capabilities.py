"""Tests for agent capability declarations and permission enforcement.

Updated for Phase 2: 3-agent architecture (tutor, planner, layout).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.agent.capabilities import (
    AGENT_CAPABILITIES,
    check_tool_permission,
    get_allowed_tools,
    check_delegation_escalation,
)
from services.agent.tools.base import ToolRegistry, ToolResult


# ── check_tool_permission ──


def test_tutor_can_search_content():
    assert check_tool_permission("tutor", "search_content") is True


def test_tutor_can_run_code():
    assert check_tool_permission("tutor", "run_code") is True


def test_tutor_can_lookup_progress():
    assert check_tool_permission("tutor", "lookup_progress") is True


def test_planner_can_list_assignments():
    assert check_tool_permission("planner", "list_assignments") is True


def test_planner_cannot_run_code():
    assert check_tool_permission("planner", "run_code") is False


def test_layout_has_no_tools():
    assert check_tool_permission("layout", "search_content") is False
    assert check_tool_permission("layout", "run_code") is False


def test_unknown_agent_is_allowed():
    """Unknown agents bypass checks (backward compat for plugins)."""
    assert check_tool_permission("custom_plugin_agent", "anything") is True


# ── get_allowed_tools ──


def test_get_allowed_tools_tutor():
    tools = get_allowed_tools("tutor")
    assert tools == AGENT_CAPABILITIES["tutor"]


def test_get_allowed_tools_layout_empty():
    tools = get_allowed_tools("layout")
    assert tools == set()


def test_get_allowed_tools_unknown_returns_none():
    assert get_allowed_tools("nonexistent_agent") is None


# ── check_delegation_escalation ──


def test_delegation_planner_to_tutor_blocked():
    """Tutor has run_code which planner lacks → blocked."""
    allowed, reason = check_delegation_escalation("planner", "tutor")
    assert allowed is False
    assert "run_code" in reason


def test_delegation_tutor_to_planner_allowed():
    """Planner is a subset of tutor's capabilities → allowed."""
    allowed, reason = check_delegation_escalation("tutor", "planner")
    assert allowed is True


def test_delegation_tutor_to_layout_allowed():
    """Layout has no tools — delegating to less-capable agent is fine."""
    allowed, reason = check_delegation_escalation("tutor", "layout")
    assert allowed is True


def test_delegation_layout_to_tutor_blocked():
    """Layout has no tools. Tutor has many → massive escalation."""
    allowed, reason = check_delegation_escalation("layout", "tutor")
    assert allowed is False


def test_delegation_unknown_agent_allowed():
    """Unknown source or target → allowed (backward compat)."""
    allowed, _ = check_delegation_escalation("unknown_agent", "tutor")
    assert allowed is True
    allowed, _ = check_delegation_escalation("tutor", "unknown_agent")
    assert allowed is True


def test_delegation_same_agent_allowed():
    """Self-delegation is always allowed."""
    allowed, _ = check_delegation_escalation("tutor", "tutor")
    assert allowed is True


# ── ToolRegistry.execute() with agent_name ──


@pytest.mark.asyncio
async def test_registry_execute_with_capability_check():
    """ToolRegistry.execute() blocks tools when agent lacks permission."""
    registry = ToolRegistry()

    mock_tool = MagicMock()
    mock_tool.name = "run_code"
    mock_tool.domain = "education"
    mock_tool.run = AsyncMock(return_value=ToolResult(success=True, output="hello"))
    registry.register(mock_tool)

    # Layout agent tries to use run_code → should be blocked
    result = await registry.execute(
        "run_code", {"code": "print('hi')"}, ctx=MagicMock(), db=MagicMock(),
        agent_name="layout",
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
        agent_name="tutor",
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

    result = await registry.execute(
        "run_code", {"code": "1+1"}, ctx=MagicMock(), db=MagicMock(),
    )
    assert result.success is True
    mock_tool.run.assert_called_once()


# ── All declared agents have valid tool names ──


def test_all_capability_tools_exist_in_builtin():
    """Every tool in AGENT_CAPABILITIES should be registered in the global tool registry."""
    from services.agent.tools.base import get_tool_registry
    from config import settings

    builtin_names = set(get_tool_registry().tool_names)

    # Tools gated behind experimental flags may not be registered
    experimental_tools: set[str] = set()
    if not settings.enable_experimental_browser:
        experimental_tools.add("web_search")
    if not settings.enable_experimental_notion_export:
        experimental_tools.add("export_notion")

    for agent, tools in AGENT_CAPABILITIES.items():
        for tool_name in tools:
            if tool_name in experimental_tools:
                continue
            assert tool_name in builtin_names, (
                f"Agent '{agent}' declares tool '{tool_name}' which is not a builtin tool. "
                f"Available: {builtin_names}"
            )
