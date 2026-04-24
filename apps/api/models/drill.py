"""Drills domain ORM — Phase 16c practice-first pivot."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base
from models.compat import CompatJSONB, CompatUUID


class DrillCourse(Base):
    """Top-level drill course (e.g. py4e, cs50p)."""

    __tablename__ = "drill_courses"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    slug: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    modules = relationship(
        "DrillModule",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="DrillModule.order_index",
    )

    __table_args__ = (Index("ix_drill_courses_slug", "slug"),)


class DrillModule(Base):
    """Ordered module inside a ``DrillCourse``."""

    __tablename__ = "drill_modules"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("drill_courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    course = relationship("DrillCourse", back_populates="modules")
    drills = relationship(
        "Drill",
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="Drill.order_index",
    )

    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="uq_drill_modules_course_slug"),
        UniqueConstraint(
            "course_id", "order_index", name="uq_drill_modules_course_order"
        ),
        Index("ix_drill_modules_course", "course_id"),
    )


class Drill(Base):
    """Single practice drill with hidden pytest tests."""

    __tablename__ = "drills"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("drill_modules.id", ondelete="CASCADE"),
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    why_it_matters: Mapped[str] = mapped_column(String(500), nullable=False)
    starter_code: Mapped[str] = mapped_column(Text, nullable=False)
    # Server-only pytest source — never surfaced to the client via schemas.
    hidden_tests: Mapped[str] = mapped_column(Text, nullable=False)
    hints: Mapped[list] = mapped_column(CompatJSONB, nullable=False, default=list)
    skill_tags: Mapped[list] = mapped_column(CompatJSONB, nullable=False, default=list)
    source_citation: Mapped[str] = mapped_column(String(300), nullable=False)
    time_budget_min: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    difficulty_layer: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1
    )

    module = relationship("DrillModule", back_populates="drills")

    __table_args__ = (
        UniqueConstraint("module_id", "slug", name="uq_drills_module_slug"),
        Index("ix_drills_module_order", "module_id", "order_index"),
        CheckConstraint(
            "difficulty_layer BETWEEN 1 AND 3",
            name="ck_drills_difficulty_range",
        ),
    )


class DrillAttempt(Base):
    """One submission of a drill by a user."""

    __tablename__ = "drill_attempts"

    id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    drill_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID,
        ForeignKey("drills.id", ondelete="CASCADE"),
        nullable=False,
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    submitted_code: Mapped[str] = mapped_column(Text, nullable=False)
    runner_output: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    drill = relationship("Drill")
    user = relationship("User")

    __table_args__ = (Index("ix_drill_attempts_user_time", "user_id", "attempted_at"),)
