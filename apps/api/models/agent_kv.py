"""General-purpose key-value store for agent working state."""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from models.compat import CompatJSONB, CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AgentKV(Base):
    """Lightweight KV store replacing ad-hoc metadata_json patterns.

    Namespaces: tutor_notes, student_profile, session_state, etc.
    """

    __tablename__ = "agent_kv"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    key: Mapped[str] = mapped_column(String(256), nullable=False)
    value_json: Mapped[dict] = mapped_column(CompatJSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "course_id", "namespace", "key", name="uq_agent_kv_user_course_ns_key"),
        Index("ix_agent_kv_user_ns", "user_id", "namespace"),
    )
