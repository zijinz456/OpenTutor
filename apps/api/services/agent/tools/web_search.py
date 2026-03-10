"""Web search tool using Tavily API.

Provides internet search capabilities for the agent when course materials
don't contain the answer or when current information is needed.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.tools.base import Tool, ToolCategory, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class WebSearchTool(Tool):
    """Search the web for current information using Tavily."""

    name = "web_search"
    description = (
        "Search the web for current information when course materials "
        "don't contain the answer. Returns titles, snippets, and source URLs. "
        "Use when the student asks about recent events, needs external "
        "references, or when RAG results are insufficient."
    )
    domain = "web"
    category = ToolCategory.READ

    def get_parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The search query to look up on the web.",
                required=True,
            ),
            ToolParameter(
                name="num_results",
                type="integer",
                description="Number of results to return (1-10). Default 5.",
                required=False,
                default=5,
            ),
        ]

    async def run(self, parameters: dict[str, Any], ctx: Any, db: AsyncSession) -> ToolResult:
        from config import settings

        query = parameters.get("query", "").strip()
        if not query:
            return ToolResult(success=False, output="", error="Search query is required.")

        try:
            num_results = min(max(int(parameters.get("num_results", 5)), 1), 10)
        except (ValueError, TypeError):
            num_results = 5

        if not settings.tavily_api_key:
            return ToolResult(
                success=False,
                output="",
                error="Web search is not configured. Set TAVILY_API_KEY to enable.",
            )

        try:
            from tavily import AsyncTavilyClient

            client = AsyncTavilyClient(api_key=settings.tavily_api_key)
            response = await client.search(query, max_results=num_results)

            results = response.get("results", [])
            if not results:
                return ToolResult(success=True, output=f"No web results found for: {query}")

            lines = [f"Web search results for: **{query}**\n"]
            for i, r in enumerate(results, 1):
                title = r.get("title", "Untitled")
                url = r.get("url", "")
                content = r.get("content", "")[:300]
                score = r.get("score", 0)
                lines.append(f"{i}. **{title}**")
                lines.append(f"   URL: {url}")
                lines.append(f"   {content}")
                if score:
                    lines.append(f"   (relevance: {score:.2f})")
                lines.append("")

            # Include answer if Tavily extracted one
            answer = response.get("answer")
            if answer:
                lines.insert(1, f"**Quick answer**: {answer}\n")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                metadata={"result_count": len(results)},
            )
        except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
            logger.exception("web_search failed: %s", e)
            return ToolResult(success=False, output="", error=f"Web search failed: {e}")
