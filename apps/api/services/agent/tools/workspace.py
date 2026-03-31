"""Workspace control tools — emit PRD-aligned block actions via the action bus.

The agent calls update_workspace with command objects. Each command is
validated and converted into block-system actions, then appended to ctx.actions.
"""

import logging
import uuid as _uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import ToolCategory, ToolResult, param, tool

logger = logging.getLogger(__name__)

VALID_SECTIONS = {"notes", "practice", "analytics", "plan"}
SECTION_PRIORITY: dict[str, str] = {
    "notes": "chapter_list,notes,quiz,flashcards,plan,progress,knowledge_graph,review,wrong_answers,forecast,agent_insight",
    "practice": "quiz,flashcards,wrong_answers,review,notes,progress,plan,knowledge_graph,chapter_list,forecast,agent_insight",
    "analytics": "progress,forecast,knowledge_graph,notes,quiz,flashcards,plan,review,wrong_answers,chapter_list,agent_insight",
    "plan": "plan,progress,review,notes,quiz,flashcards,knowledge_graph,chapter_list,wrong_answers,forecast,agent_insight",
}

VALID_COMMANDS = {
    "switch_tab", "focus_topic", "set_layout",
    "start_quiz", "generate_notes", "generate_flashcards",
}


@tool(
    name="update_workspace",
    description=(
        "Control the student's workspace using PRD action markers. "
        "Use this to prioritize sections, focus specific topics, tune block "
        "layout emphasis, and trigger content generation."
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
                'focus_topic: {"command":"focus_topic","node_id":"<real-uuid-from-content-tree>","section":"notes"} — node_id MUST be a real UUID obtained from get_course_outline or search_content, never a made-up slug. '
                'set_layout: {"command":"set_layout","chat_height":0.4,"tree_collapsed":false,"tree_width":240}. '
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
        except (ValueError, KeyError, TypeError, RuntimeError) as e:
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
        ctx.actions.append({"action": "reorder_blocks", "value": SECTION_PRIORITY[section]})
        ctx.actions.append({"action": "data_updated", "value": section})
        return f"prioritize_section({section})"

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
            ctx.actions.append({"action": "data_updated", "value": section})
        return f"focus_topic({node.title!r})"

    if command_type == "set_layout":
        emitted: list[str] = []
        if "chat_height" in cmd:
            h = float(cmd["chat_height"])
            h = max(0.15, min(0.7, h))
            size = "large" if h <= 0.25 else "medium"
            ctx.actions.append({"action": "resize_block", "value": f"notes:{size}"})
            emitted.append(f"notes->{size}")
        if "tree_collapsed" in cmd:
            collapsed = bool(cmd["tree_collapsed"])
            order = (
                "notes,quiz,flashcards,progress,plan,chapter_list,knowledge_graph,review,wrong_answers,forecast,agent_insight"
                if collapsed
                else "chapter_list,notes,quiz,flashcards,progress,plan,knowledge_graph,review,wrong_answers,forecast,agent_insight"
            )
            ctx.actions.append({"action": "reorder_blocks", "value": order})
            emitted.append("reordered")
        if "tree_width" in cmd:
            w = int(cmd["tree_width"])
            w = max(140, min(480, w))
            chapter_size = "full" if w >= 320 else "medium"
            ctx.actions.append({"action": "resize_block", "value": f"chapter_list:{chapter_size}"})
            emitted.append(f"chapter_list->{chapter_size}")
        if emitted:
            ctx.actions.append({"action": "data_updated", "value": "notes"})
            return f"set_layout_via_blocks({', '.join(emitted)})"
        return None

    if command_type == "start_quiz":
        ctx.actions.append({
            "action": "reorder_blocks",
            "value": "quiz,flashcards,wrong_answers,review,notes,progress,plan,chapter_list,knowledge_graph,forecast,agent_insight",
        })
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
