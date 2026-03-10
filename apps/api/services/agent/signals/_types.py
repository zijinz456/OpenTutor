"""Agenda signal data types.

Shared by all signal collector modules.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

SIGNAL_TYPES = (
    "active_goal",
    "deadline",
    "failed_task",
    "forgetting_risk",
    "lector_review",
    "prerequisite_gap",
    "weak_area",
    "content_stale",
    "inactivity",
    "guided_session_ready",
    "layout_adaptation",
)


@dataclass
class AgendaSignal:
    """A single signal for the agenda ranker."""

    signal_type: str          # one of SIGNAL_TYPES
    user_id: uuid.UUID
    course_id: uuid.UUID | None = None
    entity_id: str | None = None       # goal_id, task_id, assignment_id, etc.
    title: str = ""
    urgency: float = 0.0              # 0-100 normalised priority score
    detail: dict = field(default_factory=dict)
