"""Notion export tool for the agent ReAct loop.

Allows agents to export flashcards, study plans, and notes to Notion
when students request it.

Phase 2: Notion Integration
"""

import logging
import warnings
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

warnings.warn(
    "services.agent.tools.notion is dormant by default and considered experimental.",
    DeprecationWarning,
    stacklevel=2,
)


class ExportNotionTool(Tool):
    """Export flashcards or study plans to a Notion database."""

    name = "export_notion"
    description = (
        "Export the student's flashcards or study plan to Notion. "
        "Requires the student to have connected their Notion account. "
        "Use when the student says 'sync to Notion', 'export to Notion', etc."
    )
    domain = "integration"
    category = ToolCategory.WRITE

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="export_type",
                type="string",
                description="What to export: 'flashcards', 'study_plan', or 'notes'",
                required=True,
            ),
            ToolParameter(
                name="database_id",
                type="string",
                description="Target Notion database ID. If not provided, the tool will list available databases.",
                required=False,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        export_type = parameters.get("export_type", "flashcards")
        database_id = parameters.get("database_id")

        # Check if Notion is connected
        try:
            from sqlalchemy import select
            from models.integration_credential import IntegrationCredential

            result = await db.execute(
                select(IntegrationCredential).where(
                    IntegrationCredential.user_id == ctx.user_id,
                    IntegrationCredential.integration_name == "notion",
                )
            )
            credential = result.scalar_one_or_none()
        except (SQLAlchemyError, AttributeError, RuntimeError):
            logger.debug("Could not query Notion integration credential", exc_info=True)
            credential = None

        if not credential:
            return ToolResult(
                success=False,
                output="",
                error="Notion is not connected. Please connect your Notion account in Settings > Integrations first.",
            )

        token = credential.access_token

        # If no database_id, list available databases
        if not database_id:
            try:
                from services.export.notion_export import list_databases

                databases = await list_databases(token)
                if not databases:
                    return ToolResult(
                        success=False, output="",
                        error="No Notion databases found. Create a database in Notion first.",
                    )
                db_list = "\n".join(f"- {d['title']} (ID: {d['id']})" for d in databases)
                return ToolResult(
                    success=True,
                    output=f"Please specify which Notion database to use:\n{db_list}",
                    metadata={"databases": databases, "needs_selection": True},
                )
            except ImportError:
                return ToolResult(
                    success=False, output="",
                    error="notion-client package is not installed.",
                )

        # Perform the export
        try:
            if export_type == "flashcards":
                from services.export.anki_export import _load_flashcards
                cards = await _load_flashcards(db, ctx.user_id, ctx.course_id)
                card_dicts = [{"front": c["front"], "back": c["back"]} for c in cards]

                from services.export.notion_export import export_flashcards_to_notion
                result_data = await export_flashcards_to_notion(token, database_id, card_dicts)

            elif export_type == "study_plan":
                from services.export.notion_export import export_study_plan_to_notion
                # Load latest study plan from GeneratedAsset
                from models.generated_asset import GeneratedAsset
                from sqlalchemy import select as sa_select

                asset_result = await db.execute(
                    sa_select(GeneratedAsset)
                    .where(
                        GeneratedAsset.user_id == ctx.user_id,
                        GeneratedAsset.course_id == ctx.course_id,
                        GeneratedAsset.asset_type == "study_plan",
                    )
                    .order_by(GeneratedAsset.created_at.desc())
                    .limit(1)
                )
                asset = asset_result.scalar_one_or_none()
                if not asset or not asset.content:
                    return ToolResult(success=False, output="", error="No study plan found to export.")

                steps = asset.content if isinstance(asset.content, list) else [{"title": "Study Plan", "description": str(asset.content)}]
                result_data = await export_study_plan_to_notion(token, database_id, steps)
            else:
                return ToolResult(success=False, output="", error=f"Unknown export type: {export_type}")

            if result_data.get("status") == "success":
                return ToolResult(
                    success=True,
                    output=f"Exported to Notion successfully! {result_data.get('pages_created', 1)} item(s) created.",
                    metadata=result_data,
                )
            else:
                return ToolResult(success=False, output="", error=result_data.get("error", "Export failed"))

        except ImportError:
            return ToolResult(success=False, output="", error="notion-client package is not installed.")
        except (ConnectionError, TimeoutError, ValueError, KeyError, RuntimeError, OSError) as e:
            logger.exception("Notion export failed: %s", e)
            return ToolResult(success=False, output="", error=f"Notion export failed: {e}")
