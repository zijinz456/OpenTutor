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

logger = logging.getLogger(__name__)

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


# ── Graph Storage (PostgreSQL JSONB-based, upgradeable to Neo4j) ──

async def store_graph_entities(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    extracted: dict,
) -> dict:
    """Store extracted entities and relationships in the knowledge graph.

    Uses PostgreSQL JSONB for now (mem0 pattern: supports multiple backends).
    The existing knowledge graph (CourseContentTree → edges) represents static structure.
    This stores dynamic, student-specific graph data alongside it.

    Storage approach: JSONB in a dedicated table with embedding for similarity search.
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
            existing = await db.execute(
                text("""
                    SELECT id, summary, metadata_json,
                           1 - (embedding <=> :embedding::vector) as similarity
                    FROM conversation_memories
                    WHERE user_id = :user_id
                      AND memory_type = 'knowledge'
                      AND embedding IS NOT NULL
                    ORDER BY embedding <=> :embedding::vector
                    LIMIT 1
                """),
                {
                    "embedding": str(embedding),
                    "user_id": str(user_id),
                },
            )
            row = existing.fetchone()
            if row and row.similarity > 0.7:
                # Merge: increment mentions count (mem0 frequency tracking)
                meta = row.metadata_json or {}
                meta["mentions"] = meta.get("mentions", 0) + 1
                meta["last_seen"] = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    text("""
                        UPDATE conversation_memories
                        SET metadata_json = :meta, updated_at = NOW()
                        WHERE id = :id
                    """),
                    {"meta": json.dumps(meta), "id": str(row.id)},
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


# ── Learning Path Recommendations (topological sort + mastery-aware) ──


async def get_learning_path_recommendations(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[dict]:
    """Return knowledge-point nodes sorted by recommended learning order.

    Algorithm:
    1. Fetch all KnowledgePoints for the course.
    2. Fetch LearningProgress rows to build a per-node mastery map.
    3. Topological sort (Kahn's) respecting prerequisites so that nodes with
       unmet prerequisites appear before their dependents.
    4. Within the same topological level, prioritise low-mastery nodes first.
    5. Annotate each node with a human-readable ``recommended_reason``.

    Returns a list of dicts:
        {id, title, mastery_level, prerequisites, recommended_reason}
    """
    from collections import defaultdict, deque

    from models.knowledge_graph import KnowledgePoint
    from models.progress import LearningProgress

    # ── 1. Fetch knowledge points ──
    kp_result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
    )
    knowledge_points = list(kp_result.scalars().all())
    if not knowledge_points:
        return []

    kp_map: dict[str, KnowledgePoint] = {str(kp.id): kp for kp in knowledge_points}

    # ── 2. Fetch mastery data ──
    progress_result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
        )
    )
    progress_rows = progress_result.scalars().all()

    # content_node_id → mastery_score
    content_mastery: dict[str, float] = {}
    for p in progress_rows:
        if p.content_node_id:
            content_mastery[str(p.content_node_id)] = p.mastery_score

    # kp_id → effective mastery (0.0-1.0)
    mastery_map: dict[str, float] = {}
    for kp in knowledge_points:
        kp_id = str(kp.id)
        if kp.mastery_level > 0:
            mastery_map[kp_id] = kp.mastery_level / 100.0
        elif kp.source_content_node_id:
            mastery_map[kp_id] = content_mastery.get(
                str(kp.source_content_node_id), 0.0,
            )
        else:
            mastery_map[kp_id] = 0.0

    # ── 3. Topological sort (Kahn's algorithm) with level tracking ──
    forward_edges: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {str(kp.id): 0 for kp in knowledge_points}

    for kp in knowledge_points:
        kp_id = str(kp.id)
        for prereq_id in (kp.prerequisites or []):
            prereq_id = str(prereq_id)
            if prereq_id in kp_map:
                forward_edges[prereq_id].append(kp_id)
                in_degree[kp_id] += 1

    # BFS by levels so we can sort within each level by mastery
    level_groups: list[list[str]] = []
    current_level = [kp_id for kp_id, deg in in_degree.items() if deg == 0]

    while current_level:
        level_groups.append(current_level)
        next_level: list[str] = []
        for node in current_level:
            for dep in forward_edges.get(node, []):
                in_degree[dep] -= 1
                if in_degree[dep] == 0:
                    next_level.append(dep)
        current_level = next_level

    # Collect any nodes caught in cycles (in_degree never reached 0)
    visited = {kp_id for group in level_groups for kp_id in group}
    remaining = [kp_id for kp_id in kp_map if kp_id not in visited]
    if remaining:
        level_groups.append(remaining)

    # ── 4. Within each level, sort by ascending mastery (weakest first) ──
    ordered_ids: list[str] = []
    for group in level_groups:
        group.sort(key=lambda kp_id: mastery_map.get(kp_id, 0.0))
        ordered_ids.extend(group)

    # ── 5. Build result list with reasons ──
    depth_map: dict[str, int] = {}
    for level_idx, group in enumerate(level_groups):
        for kp_id in group:
            depth_map[kp_id] = level_idx

    results: list[dict] = []
    for kp_id in ordered_ids:
        kp = kp_map[kp_id]
        mastery = mastery_map.get(kp_id, 0.0)
        prereq_ids = [str(p) for p in (kp.prerequisites or []) if str(p) in kp_map]

        # Determine unmet prerequisites
        unmet = [
            pid for pid in prereq_ids
            if mastery_map.get(pid, 0.0) < 0.7
        ]

        reason = _recommendation_reason(mastery, unmet, kp_map, depth_map.get(kp_id, 0))

        results.append({
            "id": kp_id,
            "title": kp.name,
            "mastery_level": round(mastery, 3),
            "prerequisites": prereq_ids,
            "recommended_reason": reason,
        })

    return results


def _recommendation_reason(
    mastery: float,
    unmet_prereqs: list[str],
    kp_map: dict,
    depth: int,
) -> str:
    """Return a human-readable reason for this node's position in the path."""
    if unmet_prereqs:
        names = ", ".join(
            kp_map[pid].name for pid in unmet_prereqs[:3] if pid in kp_map
        )
        return f"Prerequisites not yet mastered: {names}"
    if mastery >= 0.8:
        return "Already mastered — review periodically"
    if mastery >= 0.5:
        return "Developing — reinforce with practice to reach mastery"
    if mastery > 0:
        return "Weak area — focused study recommended"
    if depth == 0:
        return "Foundational topic with no prerequisites — start here"
    return "Not yet started — begin after completing prerequisites"


# ── Mastery-Coloured Knowledge Graph ──


async def get_mastery_colored_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> list[dict]:
    """Return the knowledge graph nodes annotated with mastery-based colouring.

    Colour mapping:
        mastery >= 0.8  → "mastered"  (green)
        mastery >= 0.5  → "developing" (yellow)
        mastery <  0.5  → "weak"       (red)
        no data         → "unknown"    (gray)

    Each node dict:
        {id, title, difficulty, mastery_level, mastery_status, prerequisites, relationships}
    """
    from models.knowledge_graph import KnowledgePoint
    from models.memory import ConversationMemory
    from models.progress import LearningProgress

    # ── 1. Knowledge points ──
    kp_result = await db.execute(
        select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
    )
    knowledge_points = list(kp_result.scalars().all())
    if not knowledge_points:
        return []

    kp_map: dict[str, KnowledgePoint] = {str(kp.id): kp for kp in knowledge_points}

    # ── 2. Mastery from LearningProgress ──
    progress_result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
        )
    )
    progress_rows = progress_result.scalars().all()

    content_mastery: dict[str, float] = {}
    for p in progress_rows:
        if p.content_node_id:
            content_mastery[str(p.content_node_id)] = p.mastery_score

    # ── 3. Dynamic relationships from graph_memory entries ──
    mem_result = await db.execute(
        select(ConversationMemory)
        .where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.course_id == course_id,
            ConversationMemory.category == "Relation",
        )
        .limit(200)
    )
    dynamic_rels = mem_result.scalars().all()

    # Index dynamic relationships by entity name (lowered)
    kp_name_to_id: dict[str, str] = {
        kp.name.lower(): str(kp.id) for kp in knowledge_points
    }
    rels_by_kp: dict[str, list[dict]] = {}
    for mem in dynamic_rels:
        meta = mem.metadata_json or {}
        src_name = (meta.get("source_entity") or "").lower()
        tgt_name = (meta.get("target_entity") or "").lower()
        src_id = kp_name_to_id.get(src_name)
        tgt_id = kp_name_to_id.get(tgt_name)
        rel_type = meta.get("relation_type", "related_to")

        if src_id:
            rels_by_kp.setdefault(src_id, []).append({
                "target_id": tgt_id or tgt_name,
                "target_name": meta.get("target_entity", ""),
                "type": rel_type,
            })
        if tgt_id and tgt_id != src_id:
            rels_by_kp.setdefault(tgt_id, []).append({
                "target_id": src_id or src_name,
                "target_name": meta.get("source_entity", ""),
                "type": rel_type,
            })

    # ── 4. Build annotated node list ──
    results: list[dict] = []
    for kp in knowledge_points:
        kp_id = str(kp.id)

        # Resolve effective mastery
        has_data = False
        if kp.mastery_level > 0:
            mastery = kp.mastery_level / 100.0
            has_data = True
        elif kp.source_content_node_id:
            cid = str(kp.source_content_node_id)
            if cid in content_mastery:
                mastery = content_mastery[cid]
                has_data = True
            else:
                mastery = 0.0
        else:
            mastery = 0.0

        # Colour / status mapping
        if not has_data:
            mastery_status = "unknown"
        elif mastery >= 0.8:
            mastery_status = "mastered"
        elif mastery >= 0.5:
            mastery_status = "developing"
        else:
            mastery_status = "weak"

        # Difficulty from metadata (if present), else infer from DAG depth
        meta = kp.metadata_json or {}
        difficulty = meta.get("difficulty", None)

        prereq_ids = [str(p) for p in (kp.prerequisites or []) if str(p) in kp_map]
        relationships = rels_by_kp.get(kp_id, [])

        # Also include prerequisite edges as relationships
        for pid in prereq_ids:
            prereq = kp_map.get(pid)
            if prereq:
                relationships.append({
                    "target_id": pid,
                    "target_name": prereq.name,
                    "type": "requires",
                })

        results.append({
            "id": kp_id,
            "title": kp.name,
            "difficulty": difficulty,
            "mastery_level": round(mastery, 3),
            "mastery_status": mastery_status,
            "prerequisites": prereq_ids,
            "relationships": relationships,
        })

    return results
