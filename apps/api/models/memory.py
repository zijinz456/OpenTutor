"""Memory models for EverMemOS 3-stage pipeline (encode → consolidate → retrieve).

Uses pgvector for semantic similarity search.
Phase 0-C: conversation memory + preference context.
Phase 1: full EverMemOS with atomic facts, episode summaries, and foresight.
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Float, Integer, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ConversationMemory(Base):
    """Encoded conversation memories with vector embeddings.

    EverMemOS Stage 1 (encode): raw conversation → structured memory entry.
    Each entry stores a summary, the embedding vector, and metadata.
    """

    __tablename__ = "conversation_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=True
    )

    # Memory content
    summary: Mapped[str] = mapped_column(Text)  # Compressed/summarized memory
    memory_type: Mapped[str] = mapped_column(String(20), default="conversation")
    # Types: conversation, preference, fact, episode

    # Vector embedding (1536-dim for OpenAI ada-002, adjustable)
    embedding: Mapped[list] = mapped_column(Vector(1536), nullable=True)

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
