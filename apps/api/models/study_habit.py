"""Study habit log — records study session timing for pattern analysis."""

import uuid
from datetime import date, datetime

from sqlalchemy import Integer, Date, DateTime, ForeignKey, func, Index
from models.compat import CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class StudyHabitLog(Base):
    """Logs study session timing to learn user's preferred study schedule."""

    __tablename__ = "study_habit_logs"

    id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        CompatUUID, ForeignKey("users.id", ondelete="CASCADE")
    )

    study_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-23
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Monday

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_study_habit_user_date", "user_id", "study_date"),
    )
