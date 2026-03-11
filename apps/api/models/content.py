"""Course content tree model — stores parsed document structure (PageIndex pattern)."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Integer, Index, func
from models.compat import CompatUUID, CompatJSONB, CompatTSVECTOR, CompatVector
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# Categories that contain course metadata/logistics rather than learnable knowledge
INFO_CATEGORIES: set[str] = {"syllabus", "assignment", "exam_schedule"}


class CourseContentTree(Base):
    """Hierarchical content tree node.

    Follows PageIndex pattern: PDF → Markdown → tree structure.
    Each node represents a section/subsection of the document.
    """

    __tablename__ = "course_content_tree"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("courses.id"))
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("course_content_tree.id"), nullable=True
    )

    # Tree structure
    title: Mapped[str] = mapped_column(String(500))
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=0)  # 0=root, 1=chapter, 2=section, etc.
    order_index: Mapped[int] = mapped_column(Integer, default=0)  # Sibling ordering

    # Source info
    source_file: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_type: Mapped[str] = mapped_column(String(20), default="pdf")  # pdf, url, manual

    # Content classification: knowledge (lecture_slides, textbook, notes) vs info (assignment, exam_schedule, syllabus)
    content_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Block editor content (source of truth when present; legacy nodes use `content`)
    blocks_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)

    # Search & embedding
    search_vector: Mapped[Optional[str]] = mapped_column(CompatTSVECTOR, nullable=True)
    embedding: Mapped[Optional[list]] = mapped_column(CompatVector(1536), nullable=True)

    # Metadata
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", CompatJSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    course = relationship("Course", back_populates="content_tree")
    children = relationship("CourseContentTree", back_populates="parent", cascade="all, delete-orphan")
    parent = relationship("CourseContentTree", back_populates="children", remote_side=[id])

Index("ix_content_tree_search_vector", CourseContentTree.search_vector)
Index("ix_content_tree_course_parent", CourseContentTree.course_id, CourseContentTree.parent_id)
Index("ix_content_tree_course_order", CourseContentTree.course_id, CourseContentTree.order_index)
