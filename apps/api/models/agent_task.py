"""Durable agent task records for workflows, plans, and other long-running work."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from models.compat import CompatJSONB, CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AgentTask(Base):
    """Tracks agent work items that should be visible outside the chat stream."""

    __tablename__ = "agent_tasks"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("study_goals.id", ondelete="SET NULL"), nullable=True)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="workflow")
    input_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="read_only")
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    approval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_required")
    approval_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    checkpoint_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    step_results_json: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True)
    provenance_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agent_task_user_course_created", "user_id", "course_id", "created_at"),
        Index("ix_agent_task_user_status_created", "user_id", "status", "created_at"),
        Index("ix_agent_task_status_approval_created", "status", "requires_approval", "created_at"),
    )
