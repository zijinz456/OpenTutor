"""Interviewer Agent persistence — session + per-turn rubric/answer log.

Phase 5 introduces a dedicated interview loop (start → N turns → summary)
that lives alongside, but separately from, the chat system. Keeping the
schema in its own pair of tables (rather than reusing ``chat_sessions`` /
``chat_message_logs``) avoids leaking interview-only fields (rubric JSON,
``total_turns``, grounding source) into the chat domain and lets the UI
rehydrate a paused session without pretending it is a normal conversation.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.compat import CompatJSONB, CompatUUID


class InterviewSession(Base):
    """One interview attempt — bound to a user, optional course, and mode."""

    __tablename__ = "interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )

    # ``behavioral|technical|code_defense|mixed``
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    # ``quick|standard|deep`` — mapped to 3/10/15 total turns by the router.
    duration: Mapped[str] = mapped_column(String(20), nullable=False)
    project_focus: Mapped[str] = mapped_column(String(60), nullable=False)

    total_turns: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ``in_progress|completed|abandoned``
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_progress"
    )

    # Inline-math summary dict written when the session reaches ``completed``
    # or ``abandoned``. Kept as JSON so adding new summary fields never needs
    # a migration.
    summary_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    turns = relationship(
        "InterviewTurn",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="InterviewTurn.turn_number",
    )

    __table_args__ = (
        Index("ix_interview_sessions_user_started", "user_id", "started_at"),
    )


class InterviewTurn(Base):
    """Single Q/A exchange with rubric scores inside an ``InterviewSession``."""

    __tablename__ = "interview_turns"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # ``behavioral|technical|code_defense`` — picked by the Q generator even
    # for ``mode="mixed"`` so the grader knows which rubric schema to use.
    question_type: Mapped[str] = mapped_column(String(30), nullable=False)

    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Rubric: STAR (4 dims) for behavioral, Correctness/Depth/Tradeoff/Clarity
    # (4 dims) for technical/code_defense. Stored raw so the schema can grow
    # without a migration.
    rubric_scores_json: Mapped[Optional[dict]] = mapped_column(
        CompatJSONB, nullable=True
    )
    rubric_feedback_short: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # e.g. ``star_stories.md#story-2`` or ``code_defense_drill.md#section-3``
    grounding_source: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(60), nullable=True)
    answer_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session = relationship("InterviewSession", back_populates="turns")

    __table_args__ = (
        UniqueConstraint(
            "session_id", "turn_number", name="uq_interview_turn_session_turn"
        ),
        Index("ix_interview_turns_session_turn", "session_id", "turn_number"),
    )
