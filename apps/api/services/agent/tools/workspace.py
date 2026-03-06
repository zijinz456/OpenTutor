"""Workspace control tools — let agents drive UI state via the action bus.

The agent calls update_workspace with an array of command objects.
Each command is validated then appended to ctx.actions, which the
orchestrator forwards as SSE 'action' events to the frontend.

Supported commands:
  switch_tab        → Navigate to a section (notes, practice, analytics, plan)
  focus_topic       → Select a content node in the knowledge tree
  set_layout        → Adjust workspace dimensions (chat height, tree collapse)
  start_quiz        → Open practice section in quiz mode
  generate_notes    → Delegate to existing generate_notes tool
  generate_flashcards → Delegate to existing generate_flashcards tool
"""

import json
import logging
import uuid as _uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)

VALID_SECTIONS = {"notes", "practice", "analytics", "plan"}

VALID_COMMANDS = {
    "switch_tab", "focus_topic", "set_layout",
    "start_quiz", "generate_notes", "generate_flashcards",
}


@tool(
    name="update_workspace",
    description=(
        "Control the student's workspace UI. Use this to navigate sections, "
        "focus on specific topics in the knowledge tree, adjust layout, or "
        "trigger content generation. Pass an array of workspace commands to "
        "execute in order. Examples: switch to the practice tab, focus on a "
        "specific chapter, generate notes for a topic and show them."
    ),
    domain="workspace",
    category=ToolCategory.WRITE,
    params=[
        param(
            "commands",
            "array",
            (
                'Array of workspace command objects. Each has a "command" field '
                "plus command-specific fields. Supported commands: "
                'switch_tab: {"command":"switch_tab","section":"notes|practice|analytics|plan"}. '
                'focus_topic: {"command":"focus_topic","node_id":"<uuid>","section":"notes"}. '
                'set_layout: {"command":"set_layout","chat_height":0.4,"tree_collapsed":false}. '
                'start_quiz: {"command":"start_quiz","topic":"optional topic name"}. '
                'generate_notes: {"command":"generate_notes","topic":"topic name"}. '
                'generate_flashcards: {"command":"generate_flashcards","count":10}.'
            ),
        ),
    ],
)
async def update_workspace(
    parameters: dict[str, Any],
    ctx: Any,
    db: AsyncSession,
) -> ToolResult:
    commands = parameters.get("commands", [])
    if not isinstance(commands, list) or not commands:
        return ToolResult(success=False, output="", error="commands must be a non-empty array.")

    executed: list[str] = []
    errors: list[str] = []

    for cmd in commands:
        if not isinstance(cmd, dict):
            errors.append(f"Skipped non-object command: {cmd!r}")
            continue

        command_type = cmd.get("command", "")
        if command_type not in VALID_COMMANDS:
            errors.append(f"Unknown command: {command_type!r}")
            continue

        try:
            result = await _execute_command(command_type, cmd, ctx, db)
            if result:
                executed.append(result)
        except Exception as e:
            errors.append(f"{command_type} failed: {e}")

    summary = f"Executed {len(executed)} workspace commands: {', '.join(executed)}"
    if errors:
        summary += f". Errors: {'; '.join(errors)}"
    return ToolResult(
        success=len(executed) > 0,
        output=summary,
        error="; ".join(errors) if errors and not executed else None,
    )


async def _execute_command(
    command_type: str, cmd: dict, ctx: Any, db: AsyncSession,
) -> str | None:
    """Execute a single workspace command. Returns a description or None on error."""

    if command_type == "switch_tab":
        section = cmd.get("section", "")
        if section not in VALID_SECTIONS:
            raise ValueError(f"Invalid section: {section!r}. Valid: {VALID_SECTIONS}")
        ctx.actions.append({"action": "switch_tab", "value": section})
        return f"switch_tab({section})"

    if command_type == "focus_topic":
        node_id = str(cmd.get("node_id", "")).strip()
        section = cmd.get("section", "notes")
        if not node_id:
            raise ValueError("focus_topic requires node_id")
        # Validate node belongs to current course
        from models.content import CourseContentTree

        try:
            node = await db.get(CourseContentTree, _uuid.UUID(node_id))
        except (ValueError, Exception):
            raise ValueError(f"Invalid node_id: {node_id!r}")
        if not node or node.course_id != ctx.course_id:
            raise ValueError(f"Node {node_id} not found in current course")
        ctx.actions.append({"action": "focus_topic", "value": node_id})
        if section in VALID_SECTIONS:
            ctx.actions.append({"action": "switch_tab", "value": section})
        return f"focus_topic({node.title!r})"

    if command_type == "set_layout":
        layout_payload: dict[str, Any] = {}
        if "chat_height" in cmd:
            h = float(cmd["chat_height"])
            layout_payload["chat_height"] = max(0.15, min(0.7, h))
        if "tree_collapsed" in cmd:
            layout_payload["tree_collapsed"] = bool(cmd["tree_collapsed"])
        if "tree_width" in cmd:
            w = int(cmd["tree_width"])
            layout_payload["tree_width"] = max(140, min(480, w))
        if layout_payload:
            ctx.actions.append({
                "action": "set_layout",
                "value": json.dumps(layout_payload),
            })
            return f"set_layout({layout_payload})"
        return None

    if command_type == "start_quiz":
        ctx.actions.append({"action": "switch_tab", "value": "practice"})
        ctx.actions.append({"action": "data_updated", "value": "practice"})
        return "start_quiz()"

    if command_type == "generate_notes":
        topic = str(cmd.get("topic", "")).strip()
        if not topic:
            raise ValueError("generate_notes requires topic")
        from services.agent.tools.education import generate_notes_tool

        result = await generate_notes_tool.run(
            {"topic": topic, "format": cmd.get("format", "bullet_point")}, ctx, db,
        )
        if not result.success:
            raise RuntimeError(f"generate_notes failed: {result.error}")
        return f"generate_notes({topic!r})"

    if command_type == "generate_flashcards":
        count = int(cmd.get("count", 10))
        from services.agent.tools.education import generate_flashcards_tool

        result = await generate_flashcards_tool.run({"count": count}, ctx, db)
        if not result.success:
            raise RuntimeError(f"generate_flashcards failed: {result.error}")
        return f"generate_flashcards(count={count})"

    return None
