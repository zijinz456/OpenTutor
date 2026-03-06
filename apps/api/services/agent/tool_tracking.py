"""Tool call lifecycle tracking service.

Records tool execution events with timing for performance analysis.
Inspired by AgentFS's tool call audit trail pattern.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_OUTPUT_TRUNCATION = 2000


async def record_tool_call(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    session_id: str | None = None,
    agent_name: str,
    tool_name: str,
    input_json: dict | None = None,
    output_text: str | None = None,
    status: str = "success",
    error_message: str | None = None,
    duration_ms: float | None = None,
    iteration: int = 0,
    metadata_json: dict | None = None,
) -> None:
    """Persist a single tool call event — ToolCallEvent model removed in Phase 1.3."""
    logger.debug(
        "Tool call: %s/%s status=%s duration=%s",
        agent_name, tool_name, status, duration_ms,
    )


async def batch_record_tool_calls(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    session_id: str | None,
    agent_name: str,
    tool_calls: list[dict[str, Any]],
) -> None:
    """Batch persist tool calls — ToolCallEvent model removed in Phase 1.3."""
    if not tool_calls:
        return

    logger.debug(
        "Batch tool calls: %d calls for agent %s",
        len(tool_calls), agent_name,
    )


async def get_tool_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    days: int = 30,
) -> list[dict]:
    """Aggregate tool call statistics — ToolCallEvent model removed in Phase 1.3."""
    return []
