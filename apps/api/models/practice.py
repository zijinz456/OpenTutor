"""Practice problem and result models."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import Index, String, DateTime, ForeignKey, Text, Integer, Boolean, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PracticeProblem(Base):
    """Practice problems extracted from course content."""

    __tablename__ = "practice_problems"
    __table_args__ = (
        Index("ix_practice_problem_course", "course_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id"))
    content_node_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("course_content_tree.id"), nullable=True
    )

    # Problem data
    question_type: Mapped[str] = mapped_column(String(20))  # mc, tf, short_answer, fill_blank, matching, select_all, free_response
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)  # For MC/matching
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    # v3: Knowledge point tagging + source tracking
    knowledge_points: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True, default=list)
    source: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Sources: extracted | ai_generated | derived

    # v4: VCE-inspired diagnostic fields
    difficulty_layer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 1=basic concept recall, 2=standard application, 3=trap/edge case
    problem_metadata: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    # AI-generated structured annotation: {potential_traps, core_concept, bloom_level, ...}
    parent_problem_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("practice_problems.id"), nullable=True
    )
    is_diagnostic: Mapped[bool] = mapped_column(Boolean, default=False)
    # True for simplified "clean" versions generated for diagnostic pairs
    source_batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, nullable=True)
    source_version: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)

    # Content ownership tracking (for agent vs user content)
    source_owner: Mapped[str] = mapped_column(String(20), default="ai")
    # Values: "ai" | "user" | "ai+user_edited"
    locked: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    course = relationship("Course", back_populates="practice_problems")
    results = relationship("PracticeResult", back_populates="problem", cascade="all, delete-orphan")


class PracticeResult(Base):
    """User answers to practice problems."""

    __tablename__ = "practice_results"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    problem_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("practice_problems.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"))

    user_answer: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    ai_explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # v4: Error tracking for cross-type triangulation
    error_category: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # conceptual | procedural | computational | reading | careless
    difficulty_layer: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    answer_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    problem = relationship("PracticeProblem", back_populates="results")
