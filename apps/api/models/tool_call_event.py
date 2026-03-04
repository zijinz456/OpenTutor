"""Tool call lifecycle events for ReAct tool executions."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from models.compat import CompatJSONB, CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ToolCallEvent(Base):
    __tablename__ = "tool_call_events"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # AgentContext session_id (ephemeral)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    output_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # truncated to 2000 chars
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")  # started/success/error/skipped
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_tool_call_user_created", "user_id", "created_at"),
        Index("ix_tool_call_tool_name", "tool_name"),
    )
