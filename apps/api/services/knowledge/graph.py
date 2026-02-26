"""Knowledge graph builder from content tree.

Converts the hierarchical content tree into a graph structure
for visualization. Nodes are topics/concepts, edges are relationships.

Phase 3: Basic tree → graph conversion.
Future: LLM-extracted concept relationships (graphiti-core).
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.progress import LearningProgress

logger = logging.getLogger(__name__)


async def build_knowledge_graph(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict:
    """Build a knowledge graph from the course content tree.

    Returns D3-compatible graph format: {nodes: [...], edges: [...]}.
    Optionally enriches with learning progress data.
    """
    # Fetch all content tree nodes
    result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id)
        .order_by(CourseContentTree.level, CourseContentTree.order_index)
    )
    tree_nodes = result.scalars().all()

    if not tree_nodes:
        return {"nodes": [], "edges": []}

    # Fetch progress data if user_id provided
    progress_map: dict[str, dict] = {}
    if user_id:
        prog_result = await db.execute(
            select(LearningProgress)
            .where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        )
        for p in prog_result.scalars().all():
            if p.content_node_id:
                progress_map[str(p.content_node_id)] = {
                    "status": p.status,
                    "mastery_score": p.mastery_score,
                }

    # Build graph nodes
    nodes = []
    edges = []

    for node in tree_nodes:
        node_id = str(node.id)
        progress = progress_map.get(node_id, {"status": "not_started", "mastery_score": 0.0})

        # Determine node size by level (chapters bigger than sections)
        size = max(8, 20 - node.level * 4)

        # Color by mastery
        mastery = progress.get("mastery_score", 0.0)
        if mastery >= 0.8:
            color = "#22c55e"  # green - mastered
        elif mastery >= 0.4:
            color = "#3b82f6"  # blue - reviewed
        elif mastery > 0:
            color = "#eab308"  # yellow - in progress
        else:
            color = "#9ca3af"  # gray - not started

        nodes.append({
            "id": node_id,
            "label": node.title,
            "level": node.level,
            "size": size,
            "color": color,
            "status": progress.get("status", "not_started"),
            "mastery": mastery,
        })

        # Create edge to parent
        if node.parent_id:
            edges.append({
                "source": str(node.parent_id),
                "target": node_id,
                "type": "contains",
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "levels": max((n.level for n in tree_nodes), default=0) + 1,
        },
    }
