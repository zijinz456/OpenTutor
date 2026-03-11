"""Intervention outcome tracking — records block engine interventions and their effectiveness.

When the block decision engine fires a cognitive-load or affect-based intervention
(e.g. removing a quiz block during overload), an InterventionOutcome row is created.
Later, when cognitive load is recomputed, the outcome is resolved with the new score
so we can measure whether the intervention actually helped.

This data feeds into weight auto-tuning (Track 2.4) and the user feedback widget (Track 2.3).
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base
from models.compat import CompatUUID, CompatJSONB


class InterventionOutcome(Base):
    __tablename__ = "intervention_outcomes"
    __table_args__ = (
        Index("ix_intervention_user_course_time", "user_id", "course_id", "created_at"),
        Index("ix_intervention_unresolved", "user_id", "resolved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False,
    )

    # What intervention was fired
    intervention_type: Mapped[str] = mapped_column(
        sa.String(50), nullable=False,
    )  # "add", "remove", "update_config", "resize", "reorder"
    block_type: Mapped[str] = mapped_column(
        sa.String(50), nullable=False,
    )  # e.g. "quiz", "flashcard", "continue_cta"
    signal_source: Mapped[str] = mapped_column(
        sa.String(50), nullable=False,
    )  # e.g. "cognitive_load", "nlp_affect", "forgetting_risk"
    reason: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    # State snapshots
    cognitive_load_before: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    cognitive_load_after: Mapped[float | None] = mapped_column(sa.Float, nullable=True)

    # Resolution
    was_effective: Mapped[bool | None] = mapped_column(sa.Boolean, nullable=True)
    user_feedback: Mapped[str | None] = mapped_column(
        sa.String(20), nullable=True,
    )  # "helpful", "not_helpful", None

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True,
    )
