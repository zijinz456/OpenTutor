"""Example plugin: Web search tool.

This is a reference implementation showing how to create a custom tool plugin.
To use it, set the SERPER_API_KEY environment variable.

Move this file from plugins/examples/ to plugins/ to activate it:
    cp plugins/examples/web_search.py plugins/web_search.py
"""

import os
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

_API_KEY = os.getenv("SERPER_API_KEY", "")


class WebSearchTool(Tool):
    """Search the web using Serper API (Google Search)."""

    name = "web_search"
    description = (
        "Search the web for up-to-date information. "
        "Useful when course materials don't cover the topic or when "
        "the student asks about current events or recent developments."
    )
    domain = "general"

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="Search query.",
                required=True,
            ),
            ToolParameter(
                name="num_results",
                type="integer",
                description="Number of results to return (default 3, max 10).",
                required=False,
                default=3,
            ),
        ]

    async def run(
        self,
        parameters: dict[str, Any],
        ctx: Any,
        db: AsyncSession,
    ) -> ToolResult:
        if not _API_KEY:
            return ToolResult(
                success=False,
                output="",
                error="SERPER_API_KEY not configured. Set it in your .env file.",
            )

        query = parameters.get("query", "").strip()
        if not query:
            return ToolResult(success=False, output="", error="Empty search query.")

        num = min(int(parameters.get("num_results", 3)), 10)

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    json={"q": query, "num": num},
                    headers={"X-API-KEY": _API_KEY, "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()

            results = data.get("organic", [])[:num]
            if not results:
                return ToolResult(success=True, output="No search results found.")

            lines = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                link = r.get("link", "")
                lines.append(f"{i}. **{title}**\n   {snippet}\n   {link}\n")

            return ToolResult(
                success=True,
                output=f"Web search results for '{query}':\n\n" + "\n".join(lines),
            )

        except ImportError:
            return ToolResult(
                success=False,
                output="",
                error="httpx not installed. Run: pip install httpx",
            )
        except Exception as e:
            logger.error("Web search failed: %s", e)
            return ToolResult(success=False, output="", error=str(e))
