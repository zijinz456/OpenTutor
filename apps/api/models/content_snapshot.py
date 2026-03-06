"""Content snapshot model — stores versioned snapshots of content nodes for rollback."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, Index, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class ContentSnapshot(Base):
    """Point-in-time snapshot of a content node.

    Created automatically before agent mutations (before_agent_update),
    before user-triggered regeneration (before_regenerate), on manual save,
    or daily auto-backup. Enables rollback to any previous state.
    """

    __tablename__ = "content_snapshots"
    __table_args__ = (
        Index("ix_content_snapshot_node", "node_id"),
        Index("ix_content_snapshot_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("course_content_tree.id"), nullable=False
    )

    # Snapshot content — at least one of these should be set
    blocks_json: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    content_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Classification
    snapshot_type: Mapped[str] = mapped_column(String(30), default="auto")
    # Types: auto | manual | before_regenerate | before_agent_update | before_restore
    label: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
