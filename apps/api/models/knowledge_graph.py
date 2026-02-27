"""Knowledge graph model — knowledge points + dependency relationships.

Tracks mastery per knowledge point (distinct from LearningProgress which tracks per content node).
Extracted from course content by the graph_memory service in post-processing.
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Float, func, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class KnowledgePoint(Base):
    """Individual knowledge point within a course's knowledge graph."""

    __tablename__ = "knowledge_points"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"))

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Prerequisite knowledge point IDs (DAG structure)
    prerequisites: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True, default=list)
    # e.g. ["uuid1", "uuid2"]

    # Mastery level (0-100), computed from quiz results + FSRS retrievability
    mastery_level: Mapped[float] = mapped_column(Float, default=0.0)

    # Source content node that this knowledge point was extracted from
    source_content_node_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("course_content_tree.id"), nullable=True
    )

    metadata_json: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_kp_course", "course_id"),
        Index("ix_kp_mastery", "course_id", "mastery_level"),
    )
