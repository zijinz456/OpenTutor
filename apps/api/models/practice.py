"""Practice problem and result models."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Integer, Boolean, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class PracticeProblem(Base):
    """Practice problems extracted from course content."""

    __tablename__ = "practice_problems"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"))
    content_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_content_tree.id"), nullable=True
    )

    # Problem data
    question_type: Mapped[str] = mapped_column(String(20))  # mc, tf, short_answer, fill_blank, matching, select_all, free_response
    question: Mapped[str] = mapped_column(Text)
    options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # For MC/matching
    correct_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    course = relationship("Course", back_populates="practice_problems")
    results = relationship("PracticeResult", back_populates="problem", cascade="all, delete-orphan")


class PracticeResult(Base):
    """User answers to practice problems."""

    __tablename__ = "practice_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("practice_problems.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))

    user_answer: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(Boolean)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    problem = relationship("PracticeProblem", back_populates="results")
