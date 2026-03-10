"""Notion export service — sync flashcards, study plans, and notes to Notion.

Phase 2: External Integration
Requires `notion-client` package: pip install notion-client
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _get_notion_client(token: str):
    """Create a Notion API client. Raises ImportError if not installed."""
    from notion_client import AsyncClient  # type: ignore[import-untyped]
    return AsyncClient(auth=token)


async def list_databases(token: str) -> list[dict]:
    """List the user's Notion databases for target selection."""
    try:
        client = _get_notion_client(token)
        response = await client.search(
            filter={"value": "database", "property": "object"},
            page_size=20,
        )
        return [
            {
                "id": db["id"],
                "title": "".join(
                    t.get("plain_text", "") for t in db.get("title", [])
                ) or "Untitled",
            }
            for db in response.get("results", [])
        ]
    except ImportError:
        raise ImportError("notion-client is not installed. Run: pip install notion-client")


async def export_flashcards_to_notion(
    token: str,
    database_id: str,
    cards: list[dict],
) -> dict:
    """Export flashcards to a Notion database.

    Each card becomes a page with Front/Back properties.
    cards: list of {"front": str, "back": str, "tags": list[str]?}
    """
    try:
        client = _get_notion_client(token)
    except ImportError:
        return {"status": "error", "error": "notion-client not installed"}

    created = 0
    errors = 0

    for card in cards:
        try:
            await client.pages.create(
                parent={"database_id": database_id},
                properties={
                    "Name": {
                        "title": [{"text": {"content": card["front"][:100]}}],
                    },
                    "Front": {
                        "rich_text": [{"text": {"content": card["front"]}}],
                    },
                    "Back": {
                        "rich_text": [{"text": {"content": card["back"]}}],
                    },
                },
            )
            created += 1
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as e:
            logger.exception("Notion page creation failed for card")
            errors += 1

    return {
        "status": "success",
        "pages_created": created,
        "errors": errors,
    }


async def export_study_plan_to_notion(
    token: str,
    database_id: str,
    plan_steps: list[dict],
    course_name: str = "Study Plan",
) -> dict:
    """Export a study plan to Notion as a checklist page.

    plan_steps: list of {"title": str, "description": str, "scheduled_at": str?}
    """
    try:
        client = _get_notion_client(token)
    except ImportError:
        return {"status": "error", "error": "notion-client not installed"}

    # Create a single page with to-do blocks for each step
    children = []
    for step in plan_steps:
        children.append({
            "object": "block",
            "type": "to_do",
            "to_do": {
                "rich_text": [{"text": {"content": step.get("title", "")}}],
                "checked": False,
            },
        })
        if step.get("description"):
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"text": {"content": step["description"][:2000]}},
                    ],
                },
            })

    try:
        page = await client.pages.create(
            parent={"database_id": database_id},
            properties={
                "Name": {
                    "title": [{"text": {"content": f"OpenTutor: {course_name}"}}],
                },
            },
            children=children[:100],  # Notion limit
        )
        return {
            "status": "success",
            "page_id": page["id"],
            "url": page.get("url", ""),
        }
    except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as e:
        logger.exception("Notion study plan export failed")
        return {"status": "error", "error": str(e)}


async def export_notes_to_notion(
    token: str,
    database_id: str,
    notes: list[dict],
) -> dict:
    """Export course notes to Notion.

    notes: list of {"title": str, "content": str (markdown)}
    """
    try:
        client = _get_notion_client(token)
    except ImportError:
        return {"status": "error", "error": "notion-client not installed"}

    created = 0
    for note in notes:
        try:
            # Create page with markdown content as paragraph blocks
            content = note.get("content", "")
            # Split into chunks (Notion rich_text limit is 2000 chars)
            chunks = [content[i:i + 2000] for i in range(0, len(content), 2000)]
            children = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": chunk}}],
                    },
                }
                for chunk in chunks[:50]
            ]

            await client.pages.create(
                parent={"database_id": database_id},
                properties={
                    "Name": {
                        "title": [{"text": {"content": note.get("title", "Untitled")[:100]}}],
                    },
                },
                children=children,
            )
            created += 1
        except (OSError, ConnectionError, TimeoutError, RuntimeError, ValueError) as e:
            logger.exception("Notion note export failed")

    return {"status": "success", "pages_created": created}
