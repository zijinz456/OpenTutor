"""Knowledge graph builder — content tree + dynamic relationships.

Builds D3-compatible graph format combining:
1. Hierarchical content tree (parent-child "contains" edges)
2. Dynamic relationships from graph_memory ("related_to", "confused_with", etc.)
3. Progress-based mastery colouring

KnowledgePoint model removed in Phase 1.3 refactor.
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.memory import ConversationMemory
from models.progress import LearningProgress

logger = logging.getLogger(__name__)


async def build_knowledge_graph(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> dict:
    """Build a knowledge graph from content tree and dynamic relationships.

    Returns D3-compatible format: {nodes: [...], edges: [...], recommendations: [...]}.
    """
    # 1. Fetch content tree nodes
    tree_result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id)
        .order_by(CourseContentTree.level, CourseContentTree.order_index)
    )
    tree_nodes = tree_result.scalars().all()

    # 2. Fetch dynamic graph relationships from memory
    dynamic_edges = []
    if user_id:
        mem_result = await db.execute(
            select(ConversationMemory)
            .where(
                ConversationMemory.user_id == user_id,
                ConversationMemory.course_id == course_id,
                ConversationMemory.category == "Relation",
            )
            .limit(100)
        )
        for mem in mem_result.scalars().all():
            meta = mem.metadata_json or {}
            if meta.get("source_entity") and meta.get("target_entity"):
                dynamic_edges.append({
                    "source_name": meta["source_entity"],
                    "target_name": meta["target_entity"],
                    "type": meta.get("relation_type", "related_to"),
                })

    # 3. Fetch progress data
    progress_map: dict[str, dict] = {}
    if user_id:
        prog_result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        )
        for p in prog_result.scalars().all():
            if p.content_node_id:
                progress_map[str(p.content_node_id)] = {
                    "status": p.status,
                    "mastery_score": p.mastery_score,
                    "gap_type": p.gap_type,
                }

    # Build nodes and edges
    nodes = []
    edges = []
    node_ids = set()
    node_name_to_id: dict[str, str] = {}

    # Content tree nodes
    for node in tree_nodes:
        node_id = str(node.id)
        node_ids.add(node_id)
        progress = progress_map.get(node_id, {"status": "not_started", "mastery_score": 0.0})

        size = max(8, 20 - node.level * 4)
        mastery = progress.get("mastery_score", 0.0)
        gap_type = progress.get("gap_type")

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
            "type": "content",
            "level": node.level,
            "size": size,
            "color": color,
            "status": progress.get("status", "not_started"),
            "mastery": mastery,
            "gap_type": gap_type,
        })

        if node.parent_id:
            edges.append({
                "source": str(node.parent_id),
                "target": node_id,
                "type": "contains",
            })

        node_name_to_id[node.title.lower()] = node_id

    # Dynamic relationship edges (from graph_memory)
    for de in dynamic_edges:
        src = node_name_to_id.get(de["source_name"].lower())
        tgt = node_name_to_id.get(de["target_name"].lower())
        if src and tgt:
            edges.append({
                "source": src,
                "target": tgt,
                "type": de["type"],
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "recommendations": [],
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "content_nodes": len(tree_nodes),
            "knowledge_points": 0,
            "dynamic_relations": len(dynamic_edges),
            "levels": max((n.level for n in tree_nodes), default=0) + 1 if tree_nodes else 0,
        },
    }
