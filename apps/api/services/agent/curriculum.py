"""CurriculumAgent — course content analysis and knowledge graph extraction.

Borrows from:
- learning-agent pipeline.py: 7-step classification pipeline, SHA-256 dedup + LLM classification
- HelloAgents PlannerAgent: structured planning output
- Spec Section 4.3: Knowledge graph with DAG structure

Provides:
- Course structure analysis (chapters → sections → concepts)
- Knowledge graph prerequisite extraction
- Learning objective identification per section
- Difficulty progression mapping
"""

import logging
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.base import BaseAgent
from services.agent.react_mixin import ReActMixin
from services.agent.state import AgentContext

logger = logging.getLogger(__name__)


class CurriculumAgent(ReActMixin, BaseAgent):
    """Handles course structure analysis and knowledge graph queries."""

    name = "curriculum"
    profile = (
        "You are a curriculum analysis specialist.\n"
        "Analyze course materials to provide insights about:\n"
        "1. Knowledge graph: concepts and their prerequisite relationships\n"
        "2. Topic hierarchy: chapters → sections → key concepts\n"
        "3. Learning objectives per section\n"
        "4. Difficulty progression mapping\n"
        "Always base your analysis on the actual course content provided.\n"
        "When discussing prerequisites, be specific about which concepts depend on which."
    )
    model_preference = "large"
    react_tools = ["get_course_outline", "search_content"]

    async def _load_course_structure(self, ctx: AgentContext, db: AsyncSession) -> str:
        """Load course content tree and build a structured summary."""
        from models.content import CourseContentTree

        result = await db.execute(
            select(CourseContentTree)
            .where(CourseContentTree.course_id == ctx.course_id)
            .order_by(CourseContentTree.level, CourseContentTree.order_index)
            .limit(50)
        )
        nodes = result.scalars().all()

        if not nodes:
            return "(No course content tree found for this course)"

        lines = []
        for node in nodes:
            indent = "  " * node.level
            prefix = "#" * min(node.level + 1, 4)
            lines.append(f"{indent}{prefix} {node.title}")
            if node.content:
                # Include a snippet of content for context
                snippet = node.content[:200].replace("\n", " ")
                lines.append(f"{indent}  {snippet}")

        return "\n".join(lines)

    async def execute(self, ctx: AgentContext, db: AsyncSession) -> AgentContext:
        """Analyze course content and extract knowledge structure."""
        content_summary = await self._load_course_structure(ctx, db)

        client = self.get_llm_client()
        system_prompt = self.build_system_prompt(ctx)
        system_prompt += f"\n\n## Course Structure:\n{content_summary}"

        ctx.response, _ = await client.chat(
            system_prompt,
            ctx.user_message,
        )

        # Extract graph entities if the user asks about prerequisites or knowledge graph
        graph_keywords = ("知识图谱", "prerequisite", "前置知识", "关系图", "依赖", "knowledge graph")
        if any(kw in ctx.user_message.lower() for kw in graph_keywords):
            try:
                from services.knowledge.graph_memory import extract_graph_entities, store_graph_entities
                extracted = await extract_graph_entities(
                    content_summary[:500], ctx.response[:500],
                )
                if extracted.get("entities"):
                    await store_graph_entities(db, ctx.user_id, ctx.course_id, extracted)
                    ctx.metadata["graph_extracted"] = {
                        "entities": len(extracted.get("entities", [])),
                        "relationships": len(extracted.get("relationships", [])),
                    }
            except Exception as e:
                logger.debug("Graph extraction in curriculum agent failed: %s", e)

        return ctx

    async def stream(self, ctx: AgentContext, db: AsyncSession) -> AsyncIterator[str]:
        """Stream curriculum analysis response through the shared ReAct runtime."""
        async for chunk in ReActMixin.stream(self, ctx, db):
            yield chunk
