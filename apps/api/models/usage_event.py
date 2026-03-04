"""UsageEvent model — per-LLM-call cost tracking.

Inspired by OpenFang's UsageRecord and metering engine.
Records every LLM invocation with model, tokens, estimated cost,
and context (agent, course, scene) for aggregation and budgeting.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from models.compat import CompatJSONB, CompatUUID

from database import Base


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id = Column(CompatUUID, primary_key=True, default=uuid.uuid4)
    user_id = Column(CompatUUID, ForeignKey("users.id"), nullable=False, index=True)
    course_id = Column(CompatUUID, ForeignKey("courses.id"), nullable=True)

    # Agent context
    agent_name = Column(String(64), nullable=True)   # "teaching", "exercise", etc.
    scene = Column(String(64), nullable=True)         # "exam_prep", "study_session", etc.

    # LLM details
    model_provider = Column(String(64), nullable=False)  # "openai", "anthropic", etc.
    model_name = Column(String(128), nullable=False)     # "gpt-4o-mini", "claude-sonnet-4-6"
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost_usd = Column(Float, nullable=False, default=0.0)
    tool_calls = Column(Integer, nullable=False, default=0)

    # Metadata (intent type, swarm info, etc.)
    metadata_json = Column(CompatJSONB, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
