"""Memory models for 3-stage pipeline (encode → consolidate → retrieve).

Simplified memory types (3 types):
- profile:     About the user (learning style, weaknesses, preferences)
- knowledge:   About course content (concepts understood, questions asked)
- plan:        About learning plans (deadlines, progress, goals)

Uses embedding + keyword fallback retrieval in SQLite local mode.
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Float, Integer, func, Index
from models.compat import CompatUUID, CompatJSONB, CompatTSVECTOR, CompatVector
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


# Simplified memory types (3 types)
MEMCELL_TYPES = [
    "profile",      # About the user (learning style, weaknesses, preferences)
    "knowledge",    # About course content (concepts understood, questions asked)
    "plan",         # About learning plans (deadlines, progress, goals)
]


class ConversationMemory(Base):
    """Memory entry with rule-based classification into 3 types.

    Each entry is an atomic memory unit classified as profile, knowledge, or plan.
    Supports both vector search and BM25 keyword search (hybrid).
    """

    __tablename__ = "conversation_memories"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("courses.id"), nullable=True
    )

    # Memory content (atomic MemCell unit)
    summary: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String(20), default="conversation")

    # Category for hierarchical organization (memU pattern: Resource → Item → Category)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Vector embedding (1536-dim for OpenAI ada-002, adjustable)
    embedding: Mapped[list] = mapped_column(CompatVector(1536), nullable=True)

    # Full-text search vector for BM25 hybrid search (OpenClaw pattern)
    search_vector: Mapped[Optional[str]] = mapped_column(CompatTSVECTOR, nullable=True)

    # Scoring (EverMemOS importance × recency)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # Source context
    source_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissal_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_mem_user_type", "user_id", "memory_type"),
        Index("ix_mem_user_course", "user_id", "course_id"),
    )


# Keep index for faster keyword fallback scans on local datasets.
Index("ix_mem_search_vector", ConversationMemory.search_vector)
