"""Cognitive load baseline model — per-student behavioral baseline for relative load scoring."""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Float, Integer, func
from models.compat import CompatUUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class CognitiveBaseline(Base):
    """Persisted behavioral baseline for cognitive load calibration.

    Tracks average message length, word count, and help-seeking rate
    so that cognitive load scoring is relative to each student's norm.
    """

    __tablename__ = "cognitive_baselines"

    user_id: Mapped[uuid.UUID] = mapped_column(CompatUUID, primary_key=True)
    avg_message_length: Mapped[float] = mapped_column(Float, default=0.0)
    avg_word_count: Mapped[float] = mapped_column(Float, default=0.0)
    help_seeking_rate: Mapped[float] = mapped_column(Float, default=0.0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    session_count: Mapped[int] = mapped_column(Integer, default=0)
    # Running accumulators for online average computation
    total_length: Mapped[float] = mapped_column(Float, default=0.0)
    total_words: Mapped[float] = mapped_column(Float, default=0.0)
    help_count: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
