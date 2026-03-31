"""Agent capability declarations and permission enforcement.

Inspired by OpenFang's capability-based security model. Each agent declares
which tools it is allowed to use, and the ToolRegistry enforces this at
execution time.

The ReActMixin already limits which tools are *offered* to the LLM via
react_tools, but this module adds a second enforcement layer at the
ToolRegistry.execute() level — defense in depth.

Phase 2: Updated for 3-agent architecture (tutor, planner, layout).
"""

import logging

logger = logging.getLogger(__name__)

# ── Per-Agent Allowed Tools ──
# These mirror each agent's react_tools but serve as a centralized
# source of truth for permission checks (including non-ReAct paths).

AGENT_CAPABILITIES: dict[str, set[str]] = {
    "tutor": {
        "search_content", "lookup_progress", "get_course_outline",
        "generate_notes", "web_search", "write_file", "update_workspace",
        "get_mastery_report", "list_wrong_answers", "generate_flashcards",
        "generate_quiz", "export_anki", "derive_diagnostic",
        "list_recent_tasks", "list_study_goals", "list_assignments",
        "create_study_plan", "export_calendar", "list_files",
        "run_code", "record_comprehension", "save_user_preference",
    },
    "planner": {
        "lookup_progress", "get_mastery_report", "get_course_outline",
        "list_study_goals", "list_assignments", "create_study_plan",
        "export_calendar", "write_file", "list_files", "update_workspace",
    },
    "layout": set(),
}


def check_tool_permission(agent_name: str, tool_name: str) -> bool:
    """Check if an agent is allowed to use a specific tool.

    Returns True if allowed. Unknown agents are allowed by default
    (backward compatibility for plugins, MCP tools, etc.).
    """
    allowed = AGENT_CAPABILITIES.get(agent_name)
    if allowed is None:
        # Unknown agent — allow (backward compat)
        return True
    return tool_name in allowed


def get_allowed_tools(agent_name: str) -> set[str] | None:
    """Return the set of allowed tools for an agent.

    Returns None if the agent is unknown (no restrictions).
    """
    return AGENT_CAPABILITIES.get(agent_name)


def check_delegation_escalation(
    source_agent: str,
    target_agent: str,
) -> tuple[bool, str]:
    """Check if delegating from source to target would escalate capabilities.

    Returns (allowed, reason). Escalation = target has tools that source doesn't.
    Unknown agents are allowed (backward compat).
    """
    source_caps = AGENT_CAPABILITIES.get(source_agent)
    target_caps = AGENT_CAPABILITIES.get(target_agent)

    # If either agent is unknown, allow (backward compat)
    if source_caps is None or target_caps is None:
        return True, "Unknown agent — delegation allowed."

    escalated = target_caps - source_caps
    if escalated:
        return False, (
            f"Delegation blocked: '{target_agent}' has tools "
            f"'{source_agent}' lacks: {escalated}"
        )

    return True, "Delegation allowed — no capability escalation."
