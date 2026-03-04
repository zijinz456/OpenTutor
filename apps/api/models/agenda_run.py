"""Agenda run — thin audit record of each agent tick decision.

Records *why* the agent chose to do (or skip) something at a given tick,
making the autonomous loop explainable, dedup-friendly, and debuggable.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from models.compat import CompatJSONB, CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AgendaRun(Base):
    """One row per agenda tick evaluation."""

    __tablename__ = "agenda_runs"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    goal_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("study_goals.id", ondelete="SET NULL"), nullable=True)

    # What triggered this tick: "scheduler" | "api" | "chat_followup" | "manual"
    trigger: Mapped[str] = mapped_column(String(30), nullable=False, default="scheduler")

    # Outcome: "noop" | "queued_task" | "resumed_task" | "retried_task" | "notified" | "failed"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="noop")

    # The winning signal type (e.g. "active_goal", "forgetting_risk", "inactivity")
    top_signal_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Full signal list snapshot
    signals_json: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True)

    # The decision that was made (or "noop" reason)
    decision_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    # If we queued/resumed/retried a task, link it
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("agent_tasks.id", ondelete="SET NULL"), nullable=True)

    # Dedup key for cooldown enforcement
    dedup_key: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_agenda_run_user_created", "user_id", "created_at"),
        Index("ix_agenda_run_dedup", "user_id", "dedup_key", "created_at"),
        Index("ix_agenda_run_user_course_created", "user_id", "course_id", "created_at"),
    )
