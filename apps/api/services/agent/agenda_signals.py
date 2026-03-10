"""Agenda signal collectors -- thin re-export module.

All implementation has moved to ``services.agent.signals``.  This file
exists so that every existing ``from services.agent.agenda_signals import ...``
continues to work without changes.
"""

from services.agent.signals import (  # noqa: F401
    AgendaSignal,
    SIGNAL_TYPES,
    collect_signals,
    _collect_active_goals,
    _collect_deadlines,
    _collect_failed_tasks,
    _collect_forgetting_risk,
    _collect_prerequisite_gaps,
    _collect_weak_areas,
    _collect_content_stale,
    _collect_inactivity,
    _collect_guided_session_readiness,
    _collect_layout_adaptation,
)

__all__ = [
    "AgendaSignal",
    "SIGNAL_TYPES",
    "collect_signals",
    "_collect_active_goals",
    "_collect_deadlines",
    "_collect_failed_tasks",
    "_collect_forgetting_risk",
    "_collect_prerequisite_gaps",
    "_collect_weak_areas",
    "_collect_content_stale",
    "_collect_inactivity",
    "_collect_guided_session_readiness",
    "_collect_layout_adaptation",
]
