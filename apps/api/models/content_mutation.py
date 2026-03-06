"""Content mutation audit log — tracks all agent and user modifications to content nodes."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Index, func
from models.compat import CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ContentMutation(Base):
    """Audit record for every content modification by agents or users.

    Provides the data source for the Activity Feed on the frontend,
    showing what the agent changed, why, and linking to the pre-change snapshot.
    """

    __tablename__ = "content_mutations"
    __table_args__ = (
        Index("ix_content_mutation_node", "node_id"),
        Index("ix_content_mutation_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("course_content_tree.id"), nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("users.id"), nullable=True
    )
    agent_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # What changed
    mutation_type: Mapped[str] = mapped_column(String(30))
    # Types: rewrite_notes | add_practice | annotate | restructure | lock | unlock | restore | user_edit
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    diff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Link to pre-change snapshot for rollback
    snapshot_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("content_snapshots.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
