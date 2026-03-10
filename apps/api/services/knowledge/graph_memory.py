"""Dynamic Graph Memory — LLM-driven entity/relationship extraction from conversations.

Borrows from:
- mem0 Graph Memory: entity extraction -> relationship extraction -> graph storage -> BM25 reranking
- mem0 tools.py: EXTRACT_ENTITIES_TOOL + RELATIONS_TOOL pattern
- mem0 graph_memory.py: similarity-based node merging (threshold 0.7) + conflict resolution
- Spec Section 4.3: Knowledge graph with DAG structure

This module handles entity/relationship extraction and memory search.
Graph storage and LOOM sync operations are in graph_ops.py.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


# -- Education-specific entity and relation types --

EDUCATION_ENTITY_TYPES = [
    "Concept", "Skill", "ErrorPattern", "LearningEvent", "Resource",
]

EDUCATION_RELATIONS = [
    "requires", "reinforces", "confused_with", "mastered_via",
    "failed_because", "taught_by", "related_to",
]

# -- LLM Extraction Prompt --

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
    """Extract entities and relationships from a conversation turn."""
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

        valid_entities = [
            ent for ent in entities
            if ent.get("type") in EDUCATION_ENTITY_TYPES and ent.get("name")
        ]
        entity_names = {e["name"] for e in valid_entities}
        valid_rels = [
            rel for rel in relationships
            if (rel.get("relation") in EDUCATION_RELATIONS
                and rel.get("source") in entity_names
                and rel.get("target") in entity_names)
        ]
        return {"entities": valid_entities, "relationships": valid_rels}

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Graph entity extraction parse error: %s", e)
        return {"entities": [], "relationships": []}
    except (ConnectionError, TimeoutError, RuntimeError) as e:
        logger.exception("Graph entity extraction LLM call failed")
        return {"entities": [], "relationships": []}


def __getattr__(name):
    """Lazy re-exports for backward compat (storage moved to graph_ops.py)."""
    if name == "store_graph_entities":
        from services.knowledge.graph_ops import store_graph_entities
        return store_graph_entities
    if name == "_sync_to_knowledge_graph":
        from services.knowledge.graph_ops import sync_to_knowledge_graph
        return sync_to_knowledge_graph
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def search_graph_context(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search the dynamic knowledge graph for relevant entities and relationships."""
    from services.memory.pipeline import retrieve_memories
    return await retrieve_memories(
        db, user_id, query, course_id,
        limit=limit, memory_types=["knowledge"],
    )


async def get_learning_path_recommendations(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID,
) -> list[dict]:
    """Return learning path recommendations. KnowledgePoint model removed in Phase 1.3."""
    return []


async def get_mastery_colored_graph(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID,
) -> list[dict]:
    """Return mastery-coloured graph nodes. KnowledgePoint model removed in Phase 1.3."""
    return []
