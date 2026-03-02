"""Example plugin: Google Calendar integration (pluggy-based).

Reference implementation showing the new pluggy plugin pattern with manifest.
To use it, copy to plugins/ root and set GOOGLE_CALENDAR_CREDENTIALS.

    cp plugins/examples/google_calendar.py plugins/google_calendar.py

This demonstrates:
- MANIFEST dict for plugin metadata
- @hookimpl decorators for lifecycle hooks
- Tool registration via register_tools hook
- Integration registration via register_integrations hook
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolParameter, ToolResult
from services.plugin.hookspec import hookimpl

logger = logging.getLogger(__name__)

# ── Plugin Manifest ──

MANIFEST = {
    "name": "google-calendar",
    "version": "1.0.0",
    "description": "Google Calendar integration for study scheduling",
    "author": "OpenTutor",
    "requires": {"opentutor": ">=1.0"},
    "tools": ["create_calendar_event", "get_upcoming_exams"],
    "integrations": ["google_calendar"],
}


# ── Tools ──

class CreateCalendarEventTool(Tool):
    """Create a study event in Google Calendar."""

    name = "create_calendar_event"
    description = (
        "Create a study session or deadline event in the student's "
        "Google Calendar. Requires Google Calendar OAuth2 setup."
    )
    domain = "integration"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="title", type="string", description="Event title"),
            ToolParameter(name="start_time", type="string", description="ISO 8601 start time"),
            ToolParameter(name="duration_minutes", type="integer", description="Duration in minutes", default=60),
            ToolParameter(name="description", type="string", description="Event description", required=False),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        # Placeholder — real implementation would use Google Calendar API
        return ToolResult(
            success=False,
            output="",
            error="Google Calendar integration not configured. Set up OAuth2 credentials first.",
        )


class GetUpcomingExamsTool(Tool):
    """Scan Google Calendar for upcoming exams and deadlines."""

    name = "get_upcoming_exams"
    description = (
        "Search Google Calendar for upcoming exam/test/quiz events "
        "in the next 30 days. Helps the agent plan study sessions."
    )
    domain = "integration"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="days_ahead", type="integer", description="Number of days to look ahead", default=30),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        return ToolResult(
            success=False,
            output="",
            error="Google Calendar integration not configured.",
        )


# ── Plugin Class (pluggy hooks) ──


class GoogleCalendarPlugin:
    """Plugin implementing pluggy hooks for Google Calendar integration."""

    name = "google-calendar"

    @hookimpl
    def register_tools(self, registry):
        """Register calendar tools."""
        registry.register(CreateCalendarEventTool())
        registry.register(GetUpcomingExamsTool())
        logger.info("Google Calendar plugin: registered 2 tools")

    @hookimpl
    def register_integrations(self):
        """Declare this plugin's integration capabilities."""
        return [{
            "name": "google_calendar",
            "type": "oauth2",
            "scopes": [
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly",
            ],
            "description": "Read/write access to Google Calendar for study scheduling",
        }]

    @hookimpl
    def on_startup(self):
        logger.info("Google Calendar plugin started")

    @hookimpl
    def on_shutdown(self):
        logger.info("Google Calendar plugin stopped")
