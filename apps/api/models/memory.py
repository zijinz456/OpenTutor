"""Memory models for EverMemOS 3-stage pipeline (encode → consolidate → retrieve).

Upgraded with MemCell atomic extraction (EverMemOS pattern) and multi-type classification.

Memory types (inspired by EverMemOS 7 types + memU 6 types, adapted for education):
- episode:     Key learning event (first understood a concept, breakthrough)
- profile:     Student identity (learning style, ability level)
- preference:  Learning preference (format, pace, style)
- knowledge:   Subject knowledge memory (concept understanding)
- error:       Error pattern (common mistakes, confusion points)
- skill:       Mastered skill / technique
- fact:        Atomic fact extracted from conversation

Uses pgvector for semantic similarity + PostgreSQL full-text search for BM25.
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Float, Integer, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


# MemCell types (EverMemOS 7 types adapted for education)
MEMCELL_TYPES = [
    "episode",      # Key learning events
    "profile",      # Student identity / learning style
    "preference",   # Learning preferences
    "knowledge",    # Subject knowledge
    "error",        # Error patterns
    "skill",        # Mastered skills
    "fact",         # Atomic facts
    "conversation", # Legacy: raw conversation summaries
]


class ConversationMemory(Base):
    """MemCell-based memory with atomic extraction and multi-type classification.

    Upgraded from single-summary model to EverMemOS MemCell pattern:
    - Each entry is an atomic memory unit (not a full conversation summary)
    - Classified into one of 8 memory types for targeted retrieval
    - Supports both vector search and BM25 keyword search (hybrid)
    """

    __tablename__ = "conversation_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True
    )

    # Memory content (atomic MemCell unit)
    summary: Mapped[str] = mapped_column(Text)
    memory_type: Mapped[str] = mapped_column(String(20), default="conversation")

    # Category for hierarchical organization (memU pattern: Resource → Item → Category)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Vector embedding (1536-dim for OpenAI ada-002, adjustable)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=True)

    # Full-text search vector for BM25 hybrid search (OpenClaw pattern)
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)

    # Scoring (EverMemOS importance × recency)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, default=0)

    # Source context
    source_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_mem_user_type", "user_id", "memory_type"),
        Index("ix_mem_user_course", "user_id", "course_id"),
        Index("ix_mem_search_vector", "search_vector", postgresql_using="gin"),
    )
