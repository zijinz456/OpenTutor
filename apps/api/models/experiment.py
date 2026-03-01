"""A/B testing experiment model.

Tracks experiments, variants, and user assignments for comparing
different prompts, models, and teaching strategies.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime, Float, Integer, Boolean, ForeignKey, Text, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Experiment(Base):
    """An A/B test experiment definition."""

    __tablename__ = "experiments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # What is being tested: "prompt", "model", "strategy", "temperature", etc.
    dimension: Mapped[str] = mapped_column(String(50), nullable=False)

    # Variant definitions: [{"id": "control", "config": {...}}, {"id": "treatment", "config": {...}}]
    variants: Mapped[list] = mapped_column(JSONB, nullable=False)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Traffic allocation (0.0-1.0): fraction of users enrolled in this experiment
    traffic_fraction: Mapped[float] = mapped_column(Float, default=1.0)

    # Success metric: "response_quality", "mastery_gain", "engagement", "quiz_accuracy"
    primary_metric: Mapped[str] = mapped_column(String(50), default="response_quality")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_exp_active", "is_active"),
        Index("ix_exp_dimension", "dimension"),
    )


class ExperimentAssignment(Base):
    """Tracks which variant a user is assigned to for an experiment."""

    __tablename__ = "experiment_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("experiments.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    variant_id: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "control" or "treatment"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ea_user_exp", "user_id", "experiment_id", unique=True),
    )


class ExperimentEvent(Base):
    """Records metric events for experiment analysis."""

    __tablename__ = "experiment_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("experiments.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    variant_id: Mapped[str] = mapped_column(String(50), nullable=False)

    metric_name: Mapped[str] = mapped_column(String(50), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)

    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ee_exp_metric", "experiment_id", "metric_name"),
        Index("ix_ee_user", "user_id"),
    )
