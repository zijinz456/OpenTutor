"""Calendar export tool for the agent ReAct loop.

Allows agents to offer iCal downloads when students want to sync study plans
with their calendar apps.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class ExportCalendarTool(Tool):
    """Export a study plan as an iCal (.ics) file for calendar import."""

    name = "export_calendar"
    description = (
        "Export the student's study plan as an iCal (.ics) file. "
        "Returns a download link that can be imported into Google Calendar, "
        "Apple Calendar, Outlook, etc. Use when the student asks to sync "
        "their study plan with a calendar."
    )
    domain = "education"
    category = ToolCategory.READ

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="plan_batch_id",
                type="string",
                description="Optional batch ID for a specific study plan. Leave empty to export the most recent plan.",
                required=False,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        try:
            import uuid

            plan_batch_id = parameters.get("plan_batch_id")
            pid = uuid.UUID(plan_batch_id) if plan_batch_id else None

            from services.export.calendar_export import export_study_plan_to_ical

            filepath = await export_study_plan_to_ical(
                db, ctx.user_id, ctx.course_id, plan_batch_id=pid
            )

            url = f"/api/export/calendar?course_id={ctx.course_id}"
            if pid:
                url += f"&plan_batch_id={pid}"

            return ToolResult(
                success=True,
                output=f"Study plan exported to iCal! Download: {url}",
                metadata={"download_url": url, "filepath": str(filepath)},
            )
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))
        except (IOError, OSError, RuntimeError, KeyError) as e:
            logger.exception("export_calendar failed: %s", e)
            return ToolResult(success=False, output="", error=f"Calendar export failed: {e}")
