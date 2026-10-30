"""LOOM sync operations.

Syncs conversation-extracted relationships to the static LOOM knowledge graph.
"""

import logging
import inspect
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Map dynamic relation types to LOOM edge types
_RELATION_MAP = {
    "confused_with": "confused_with",
    "requires": "prerequisite",
    "reinforces": "related",
    "related_to": "related",
    "failed_because": "prerequisite",
    "mastered_via": "related",
    "taught_by": "related",
}


async def sync_to_knowledge_graph(
    db: AsyncSession,
    course_id: uuid.UUID,
    extracted: dict,
) -> int:
    """Sync conversation-extracted relationships to the LOOM static graph.

    If both source and target entity names match existing KnowledgeNode names
    for this course, create a KnowledgeEdge linking them.
    """
    relationships = extracted.get("relationships", [])
    if not relationships or not course_id:
        return 0

    try:
        from models.knowledge_graph import KnowledgeNode, KnowledgeEdge

        result = await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
        )
        nodes = result.scalars().all()
        if not nodes:
            return 0

        node_by_name = {n.name.lower(): n for n in nodes}
        synced = 0

        for rel in relationships:
            source_name = rel.get("source", "").lower()
            target_name = rel.get("target", "").lower()
            rel_type = rel.get("relation", "")

            source_node = node_by_name.get(source_name)
            target_node = node_by_name.get(target_name)
            edge_type = _RELATION_MAP.get(rel_type)

            if not source_node or not target_node or not edge_type:
                continue
            if source_node.id == target_node.id:
                continue

            existing = await db.execute(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.source_id == source_node.id,
                    KnowledgeEdge.target_id == target_node.id,
                    KnowledgeEdge.relation_type == edge_type,
                )
            )
            if existing.scalar_one_or_none():
                continue

            edge = KnowledgeEdge(
                source_id=source_node.id,
                target_id=target_node.id,
                relation_type=edge_type,
                weight=1.0,
            )
            add_result = db.add(edge)
            if inspect.isawaitable(add_result):
                await add_result

            if edge_type == "confused_with":
                reverse = KnowledgeEdge(
                    source_id=target_node.id,
                    target_id=source_node.id,
                    relation_type=edge_type,
                    weight=1.0,
                )
                add_result = db.add(reverse)
                if inspect.isawaitable(add_result):
                    await add_result

            synced += 1

        if synced:
            await db.flush()
        return synced

    except (ImportError, KeyError, ValueError, OSError) as e:
        logger.debug("LOOM graph sync failed (non-critical): %s", e)
        return 0
