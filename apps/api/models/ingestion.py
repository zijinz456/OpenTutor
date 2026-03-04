"""Ingestion job tracking model.

Tracks all data ingestion tasks with:
- SHA-256 content hash for dedup (Papra pattern)
- course_preset for skipping classification
- dispatched flag for tracking which business tables received data
- User correction records for learning

Reference: Papra hash-during-stream + DB unique constraint
"""

import uuid
from typing import Optional
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import String, DateTime, ForeignKey, Text, Boolean, Integer, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class IngestionJob(Base):
    """Tracks file/URL ingestion through the classification pipeline."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"))

    # Source info
    source_type: Mapped[str] = mapped_column(String(20))  # file | url | canvas
    original_filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Dedup (Papra pattern: SHA-256 hash-during-stream)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Classification results
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    course_preset: Mapped[bool] = mapped_column(Boolean, default=False)  # User pre-assigned
    content_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Categories: lecture_slides, textbook, assignment, exam_schedule, syllabus, notes, other
    classification_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # Methods: filename_regex, user_preset, llm_classification

    # Pipeline status
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Status: pending, uploaded, extracting, classifying, dispatching, embedding, completed, failed
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    phase_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    embedding_status: Mapped[str] = mapped_column(String(20), default="pending")
    # Embedding status: pending, running, completed, failed
    nodes_created: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Dispatch tracking
    dispatched: Mapped[bool] = mapped_column(Boolean, default=False)
    dispatched_to: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    # e.g. {"content_tree": "uuid", "assignments": "uuid"}

    # User corrections (for learning)
    user_corrected_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    user_corrected_course: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, nullable=True
    )

    # Extracted content (intermediate)
    extracted_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class StudySession(Base):
    """Tracks study sessions for learning progress."""

    __tablename__ = "study_sessions"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"))

    # Session metrics
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Activity tracking
    messages_sent: Mapped[int] = mapped_column(Integer, default=0)
    problems_attempted: Mapped[int] = mapped_column(Integer, default=0)
    problems_correct: Mapped[int] = mapped_column(Integer, default=0)
    notes_viewed: Mapped[int] = mapped_column(Integer, default=0)

    # Preference signals extracted
    signals_extracted: Mapped[int] = mapped_column(Integer, default=0)

    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)


class Assignment(Base):
    """Course assignments extracted from ingestion pipeline."""

    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"))

    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    assignment_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    # Types: homework, quiz, exam, project, reading

    source_ingestion_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("ingestion_jobs.id"), nullable=True
    )

    status: Mapped[str] = mapped_column(String(20), default="active")
    # Status: active, submitted, graded

    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WrongAnswer(Base):
    """Wrong answers for review system (Phase 1 WF-5)."""

    __tablename__ = "wrong_answers"
    __table_args__ = (
        sa.Index("ix_wrong_answers_user_course", "user_id", "course_id"),
        sa.Index("ix_wrong_answers_course_mastered", "course_id", "mastered"),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    problem_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("practice_problems.id", ondelete="CASCADE"))
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"))

    user_answer: Mapped[str] = mapped_column(Text)
    correct_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # v3: Error classification and knowledge point tagging
    error_category: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # Categories: conceptual | procedural | computational | reading | careless
    knowledge_points: Mapped[Optional[list]] = mapped_column(CompatJSONB, nullable=True, default=list)
    # List of knowledge point IDs related to this wrong answer

    # v4: Diagnostic pair result + structured error detail
    diagnosis: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    # fundamental_gap | trap_vulnerability | carelessness | mastered (from diagnostic pair)
    error_detail: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    # Structured classification: {category, confidence, evidence, related_concept}

    # Review tracking
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    mastered: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
