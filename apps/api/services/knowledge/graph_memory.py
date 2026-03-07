"""Dynamic Graph Memory — LLM-driven entity/relationship extraction from conversations.

Borrows from:
- mem0 Graph Memory: entity extraction → relationship extraction → graph storage → BM25 reranking
- mem0 tools.py: EXTRACT_ENTITIES_TOOL + RELATIONS_TOOL pattern
- mem0 graph_memory.py: similarity-based node merging (threshold 0.7) + conflict resolution
- Spec Section 4.3: Knowledge graph with DAG structure

This module extends the existing static knowledge graph (content tree → DAG)
with dynamic relationships extracted from student conversations:
- (Concept) -[confused_with]-> (Concept)
- (Concept) -[failed_because]-> (Prerequisite)
- (Concept) -[mastered_via]-> (Teaching Method)
- (Concept) -[requires]-> (Prerequisite)

The dynamic graph complements the static DAG to create a complete learning knowledge graph.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from services.llm.router import get_llm_client
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

# ── Education-specific entity and relation types ──

EDUCATION_ENTITY_TYPES = [
    "Concept",         # Knowledge concept (eigenvalue, limit, derivative)
    "Skill",           # Technique (matrix multiplication, integration by parts)
    "ErrorPattern",    # Error type (concept confusion, calculation error)
    "LearningEvent",   # Milestone (first understanding, breakthrough)
    "Resource",        # Learning resource (Chapter 3.2, Exercise Set 5)
]

EDUCATION_RELATIONS = [
    "requires",        # A is prerequisite for B
    "reinforces",      # A strengthens understanding of B
    "confused_with",   # Student confuses A and B
    "mastered_via",    # Student mastered B through method A
    "failed_because",  # Error in B because of weakness in A
    "taught_by",       # B learned through resource A
    "related_to",      # Generic relation
]

# ── LLM Extraction Prompts (adapted from mem0 tools.py) ──

ENTITY_EXTRACTION_PROMPT = """Extract educational entities and their relationships from this conversation.

Entity types: Concept, Skill, ErrorPattern, LearningEvent, Resource
Relationship types: requires, reinforces, confused_with, mastered_via, failed_because, taught_by, related_to

Conversation:
Student: {user_message}
Tutor: {assistant_response}

Course: {course_name}

Output JSON:
{{
  "entities": [
    {{"name": "<entity name>", "type": "<entity type>", "description": "<brief description>"}}
  ],
  "relationships": [
    {{"source": "<entity name>", "relation": "<relation type>", "target": "<entity name>"}}
  ]
}}

Rules:
- Only extract entities/relations that are clearly evident in the conversation
- Names should be concise (1-4 words)
- If no educational entities found, return {{"entities": [], "relationships": []}}
- Focus on: concepts discussed, errors made, skills demonstrated, breakthroughs"""


async def extract_graph_entities(
    user_message: str,
    assistant_response: str,
    course_name: str = "",
) -> dict:
    """Extract entities and relationships from a conversation turn.

    mem0 EXTRACT_ENTITIES_TOOL + RELATIONS_TOOL pattern, combined into one call.
    """
    client = get_llm_client("fast")
    try:
        result, _ = await client.extract(
            "You are an educational knowledge graph extractor. Output valid JSON.",
            ENTITY_EXTRACTION_PROMPT.format(
                user_message=user_message[:500],
                assistant_response=assistant_response[:500],
                course_name=course_name[:100],
            ),
        )
        result = result.strip()
        if "```" in result:
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]

        data = json.loads(result)
        entities = data.get("entities", [])
        relationships = data.get("relationships", [])

        # Validate entity types
        valid_entities = []
        for ent in entities:
            if ent.get("type") in EDUCATION_ENTITY_TYPES and ent.get("name"):
                valid_entities.append(ent)

        # Validate relationship types
        valid_rels = []
        entity_names = {e["name"] for e in valid_entities}
        for rel in relationships:
            if (rel.get("relation") in EDUCATION_RELATIONS
                    and rel.get("source") in entity_names
                    and rel.get("target") in entity_names):
                valid_rels.append(rel)

        return {"entities": valid_entities, "relationships": valid_rels}

    except Exception as e:
        logger.debug("Graph entity extraction failed: %s", e)
        return {"entities": [], "relationships": []}


# ── Graph Storage (JSON-based, upgradeable to graph DB) ──

async def store_graph_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    extracted: dict,
) -> dict:
    """Store extracted entities and relationships in the knowledge graph.

    The existing knowledge graph (CourseContentTree → edges) represents static structure.
    This stores dynamic, student-specific graph data alongside it.

    Storage approach: JSON in a dedicated table with embedding for similarity search.
    Can be upgraded to Neo4j/Kuzu following mem0's graph_store pattern.
    """
    from models.memory import ConversationMemory

    entities = extracted.get("entities", [])
    relationships = extracted.get("relationships", [])

    if not entities and not relationships:
        return {"stored_entities": 0, "stored_relationships": 0}

    # Store as a graph memory entry (MemCell with type = "knowledge")
    for entity in entities:
        summary = f"[{entity['type']}] {entity['name']}: {entity.get('description', '')}"
        from services.memory.pipeline import generate_embedding
        embedding = await generate_embedding(summary)

        # Check for existing similar entity (mem0 similarity merge, threshold 0.7)
        if embedding:
            row = await _find_similar_memory(db, user_id, embedding)
            if row and row.get("similarity", 0) > 0.7:
                # Merge: increment mentions count (mem0 frequency tracking)
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

        # Create new entity memory
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
        db.add(mem)

    # Store relationships as separate entries for searchability
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
        db.add(mem)

    await db.flush()

    logger.info(
        "Graph stored: %d entities, %d relationships for user %s",
        len(entities), len(relationships), user_id,
    )
    return {
        "stored_entities": len(entities),
        "stored_relationships": len(relationships),
    }


async def search_graph_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search the dynamic knowledge graph for relevant entities and relationships.

    Uses vector similarity + entity name keyword matching (mem0 BM25 reranking pattern).
    """
    from services.memory.pipeline import retrieve_memories

    results = await retrieve_memories(
        db, user_id, query, course_id,
        limit=limit,
        memory_types=["knowledge"],
    )
    return results


# ── Learning Path Recommendations ──


async def get_learning_path_recommendations(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[dict]:
    """Return learning path recommendations.

    KnowledgePoint model removed in Phase 1.3 — returns empty list.
    """
    return []


# ── Mastery-Coloured Knowledge Graph ──


async def get_mastery_colored_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[dict]:
    """Return mastery-coloured graph nodes.

    KnowledgePoint model removed in Phase 1.3 — returns empty list.
    """
    return []
