"""Course model."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[Optional[dict]] = mapped_column("metadata", CompatJSONB, nullable=True)

    # v3: Scene system — Course serves as Project
    active_scene: Mapped[Optional[str]] = mapped_column(String(50), default="study_session", nullable=True)
    template_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user = relationship("User", back_populates="courses")
    content_tree = relationship("CourseContentTree", back_populates="course", cascade="all, delete-orphan")
    practice_problems = relationship("PracticeProblem", back_populates="course", cascade="all, delete-orphan")
