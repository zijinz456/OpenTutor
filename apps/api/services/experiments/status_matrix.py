"""Runtime integration status matrix for experimental modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from config import settings

IntegrationStatus = Literal["active", "dormant", "deprecated"]


@dataclass(frozen=True)
class IntegrationState:
    status: IntegrationStatus
    owner: str
    notes: str


def get_integration_status_matrix() -> dict[str, IntegrationState]:
    """Return current integration states for experimental/sunset modules."""
    notion_status: IntegrationStatus = "active" if settings.enable_experimental_notion_export else "dormant"
    return {
        "loom": IntegrationState(
            status="active" if settings.enable_experimental_loom else "dormant",
            owner="learning_science",
            notes="Mastery graph and cross-course linking are wired into proactive jobs.",
        ),
        "lector": IntegrationState(
            status="active" if settings.enable_experimental_lector else "dormant",
            owner="learning_science",
            notes="Heartbeat reminders and review summaries are in active scheduler flow.",
        ),
        "notion_export": IntegrationState(
            status=notion_status,
            owner="integrations",
            notes="Tool exists but is gated behind ENABLE_EXPERIMENTAL_NOTION_EXPORT.",
        ),
        "legacy_stream_events": IntegrationState(
            status="deprecated",
            owner="agent_runtime",
            notes="Kept as compatibility shim; orchestrator emits raw SSE dict events.",
        ),
        "session_export_sqlite": IntegrationState(
            status="deprecated",
            owner="data_portability",
            notes="No active route/tool entrypoint; retained for migration window.",
        ),
    }

