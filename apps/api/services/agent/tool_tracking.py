"""Tool call lifecycle tracking service.

Records tool execution events with timing for performance analysis.
Inspired by AgentFS's tool call audit trail pattern.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

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
    """Persist a single tool call event."""
    from models.tool_call_event import ToolCallEvent

    event = ToolCallEvent(
        user_id=user_id,
        course_id=course_id,
        session_id=session_id,
        agent_name=agent_name,
        tool_name=tool_name,
        input_json=input_json,
        output_text=(output_text[:_OUTPUT_TRUNCATION] if output_text else None),
        status=status,
        error_message=error_message,
        duration_ms=duration_ms,
        iteration=iteration,
        metadata_json=metadata_json,
    )
    db.add(event)
    await db.commit()


async def batch_record_tool_calls(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    session_id: str | None,
    agent_name: str,
    tool_calls: list[dict[str, Any]],
) -> None:
    """Batch persist tool calls from ctx.tool_calls after a ReAct session."""
    from models.tool_call_event import ToolCallEvent

    if not tool_calls:
        return

    for tc in tool_calls:
        output = tc.get("output", "")
        event = ToolCallEvent(
            user_id=user_id,
            course_id=course_id,
            session_id=session_id,
            agent_name=agent_name,
            tool_name=tc.get("tool", "unknown"),
            input_json=tc.get("input"),
            output_text=(output[:_OUTPUT_TRUNCATION] if output else None),
            status="success" if tc.get("success") else "error",
            error_message=tc.get("error"),
            duration_ms=tc.get("duration_ms"),
            iteration=tc.get("iteration", 0),
        )
        db.add(event)

    await db.commit()


async def get_tool_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    days: int = 30,
) -> list[dict]:
    """Aggregate tool call statistics per tool name."""
    query = text("""
        SELECT
            tool_name,
            COUNT(*) as total_calls,
            COUNT(*) FILTER (WHERE status = 'success') as successful,
            COUNT(*) FILTER (WHERE status = 'error') as failed,
            ROUND(AVG(duration_ms)::numeric, 1) as avg_duration_ms,
            ROUND(MAX(duration_ms)::numeric, 1) as max_duration_ms
        FROM tool_call_events
        WHERE user_id = :user_id
          AND created_at > NOW() - make_interval(days => :days)
        GROUP BY tool_name
        ORDER BY total_calls DESC
    """)

    result = await db.execute(query, {"user_id": user_id, "days": days})
    rows = result.fetchall()
    return [
        {
            "tool_name": r[0],
            "total_calls": r[1],
            "successful": r[2],
            "failed": r[3],
            "avg_duration_ms": float(r[4]) if r[4] else None,
            "max_duration_ms": float(r[5]) if r[5] else None,
        }
        for r in rows
    ]
