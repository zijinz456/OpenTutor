"""Graph storage and LOOM sync operations.

Stores extracted entities/relationships in the knowledge graph and syncs
conversation-extracted relationships to the static LOOM knowledge graph.
"""

import json
import logging
import inspect
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.search.compat import cosine_similarity as _cosine

logger = logging.getLogger(__name__)


async def _find_similar_memory(db, user_id, embedding) -> dict | None:
    """Find the most similar knowledge memory by embedding."""
    from models.memory import ConversationMemory

    result = await db.execute(
        select(ConversationMemory).where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.memory_type == "knowledge",
            ConversationMemory.embedding.isnot(None),
        )
    )
    memories = result.scalars().all()

    best, best_sim = None, 0.0
    for mem in memories:
        emb = mem.embedding
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except (json.JSONDecodeError, TypeError):
                continue
        if not emb:
            continue
        sim = _cosine(embedding, emb)
        if sim > best_sim:
            best, best_sim = mem, sim
    if best:
        return {
            "id": str(best.id),
            "summary": best.summary,
            "metadata_json": best.metadata_json,
            "similarity": best_sim,
        }
    return None

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


async def store_graph_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    extracted: dict,
) -> dict:
    """Store extracted entities and relationships in the knowledge graph.

    Storage approach: JSON in a dedicated table with embedding for similarity search.
    Can be upgraded to Neo4j/Kuzu following mem0's graph_store pattern.
    """
    from models.memory import ConversationMemory
    from services.memory.pipeline import generate_embedding

    entities = extracted.get("entities", [])
    relationships = extracted.get("relationships", [])

    if not entities and not relationships:
        return {"stored_entities": 0, "stored_relationships": 0}

    for entity in entities:
        summary = f"[{entity['type']}] {entity['name']}: {entity.get('description', '')}"
        embedding = await generate_embedding(summary)

        # Check for existing similar entity (mem0 similarity merge, threshold 0.7)
        if embedding:
            row = await _find_similar_memory(db, user_id, embedding)
            if row and row.get("similarity", 0) > 0.7:
                meta = row.get("metadata_json") or {}
                meta["mentions"] = meta.get("mentions", 0) + 1
                meta["last_seen"] = datetime.now(timezone.utc).isoformat()
                now_str = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    text("""
                        UPDATE conversation_memories
                        SET metadata_json = :meta, updated_at = :now
                        WHERE id = :id
                    """),
                    {"meta": json.dumps(meta), "id": row["id"], "now": now_str},
                )
                continue

        mem = ConversationMemory(
            user_id=user_id,
            course_id=course_id,
            summary=summary,
            memory_type="knowledge",
            category=entity["type"],
            embedding=embedding,
            importance=0.6,
            metadata_json={
                "entity_type": entity["type"],
                "entity_name": entity["name"],
                "mentions": 1,
                "relationships": [
                    r for r in relationships
                    if r["source"] == entity["name"] or r["target"] == entity["name"]
                ],
            },
        )
        add_result = db.add(mem)
        if inspect.isawaitable(add_result):
            await add_result

    for rel in relationships:
        summary = f"[Relation] ({rel['source']}) -[{rel['relation']}]-> ({rel['target']})"
        embedding = await generate_embedding(summary)
        mem = ConversationMemory(
            user_id=user_id,
            course_id=course_id,
            summary=summary,
            memory_type="knowledge",
            category="Relation",
            embedding=embedding,
            importance=0.5,
            metadata_json={
                "relation_type": rel["relation"],
                "source_entity": rel["source"],
                "target_entity": rel["target"],
                "mentions": 1,
            },
        )
        add_result = db.add(mem)
        if inspect.isawaitable(add_result):
            await add_result

    await db.flush()

    synced = await sync_to_knowledge_graph(db, course_id, extracted)

    logger.info(
        "Graph stored: %d entities, %d relationships for user %s (synced %d to LOOM)",
        len(entities), len(relationships), user_id, synced,
    )
    return {
        "stored_entities": len(entities),
        "stored_relationships": len(relationships),
        "synced_to_loom": synced,
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
