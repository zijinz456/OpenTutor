"""LOOM-inspired knowledge graph — concept nodes with mastery and relationships.

Based on: "LOOM: Learner-Oriented Ontology Memory" (arxiv:2511.21037)

Tracks individual concepts (not content nodes) with per-user mastery scores
and inter-concept relationships (prerequisite, related, confused_with).
"""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Float, Integer, func, UniqueConstraint
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class KnowledgeNode(Base):
    """A concept in the knowledge graph (e.g., 'Chain Rule', 'Depreciation')."""

    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint("course_id", "name", name="uq_knowledge_node_course_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Linked content node (optional — maps concept to curriculum position)
    content_node_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("course_content_tree.id", ondelete="SET NULL"), nullable=True
    )

    # Metadata from extraction
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", CompatJSONB, nullable=True)
    # e.g. {"bloom_level": 2, "source": "auto_extracted", "frequency": 5}

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeEdge(Base):
    """A relationship between two concepts."""

    __tablename__ = "knowledge_edges"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation_type", name="uq_knowledge_edge"),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"))
    target_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"))

    relation_type: Mapped[str] = mapped_column(String(30))
    # prerequisite | related | confused_with | part_of

    weight: Mapped[float] = mapped_column(Float, default=1.0)
    # Confidence/frequency of this relationship

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConceptMastery(Base):
    """Per-user mastery of a concept (aggregated from practice + quiz results)."""

    __tablename__ = "concept_mastery"
    __table_args__ = (
        UniqueConstraint("user_id", "knowledge_node_id", name="uq_concept_mastery_user_node"),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    knowledge_node_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("knowledge_nodes.id", ondelete="CASCADE")
    )

    mastery_score: Mapped[float] = mapped_column(Float, default=0.0)
    # 0.0 = unknown, 1.0 = fully mastered

    practice_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)

    # FSRS-style retention tracking
    last_practiced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    next_review_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stability_days: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
