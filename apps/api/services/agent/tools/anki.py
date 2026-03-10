"""Anki export tool for the agent ReAct loop.

Allows agents to offer Anki deck downloads when students request flashcard export.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class ExportAnkiTool(Tool):
    """Export flashcards to an Anki .apkg file for download."""

    name = "export_anki"
    description = (
        "Export the student's flashcards as an Anki .apkg file. "
        "Returns a download link. Use when the student asks to export "
        "flashcards to Anki or wants to study with Anki."
    )
    domain = "education"
    category = ToolCategory.READ  # Read-only: generates file, doesn't modify data

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="batch_id",
                type="string",
                description="Optional batch ID to export a specific flashcard set. Leave empty to export all flashcards for the current course.",
                required=False,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        try:
            import uuid

            batch_id = parameters.get("batch_id")
            bid = uuid.UUID(batch_id) if batch_id else None

            from services.export.anki_export import export_flashcards_to_anki

            filepath = await export_flashcards_to_anki(
                db, ctx.user_id, ctx.course_id, batch_id=bid
            )

            # Return a download URL the frontend can use
            url = f"/api/export/anki?course_id={ctx.course_id}"
            if bid:
                url += f"&batch_id={bid}"

            return ToolResult(
                success=True,
                output=f"Anki deck exported successfully! Download: {url}",
                metadata={"download_url": url, "filepath": str(filepath)},
            )
        except ValueError as e:
            return ToolResult(success=False, output="", error=str(e))
        except (IOError, OSError, RuntimeError, KeyError) as e:
            logger.exception("export_anki failed: %s", e)
            return ToolResult(success=False, output="", error=f"Anki export failed: {e}")
