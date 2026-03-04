"""Archived learning report model — stores generated daily/weekly reports."""

import uuid
from typing import Optional
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Text, func
from models.compat import CompatUUID, CompatJSONB
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Report(Base):
    """Persisted learning report (daily brief or weekly summary)."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, ForeignKey("users.id", ondelete="CASCADE"))
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        CompatUUID, ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    report_type: Mapped[str] = mapped_column(String(30))  # "daily_brief" | "weekly_report"
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content: Mapped[str] = mapped_column(Text)
    data_snapshot: Mapped[Optional[dict]] = mapped_column(CompatJSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
