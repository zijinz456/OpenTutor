"""LOOM extraction — concept extraction from course content via LLM.

Extracts concepts, prerequisites, and relationships from educational content
and stores them as KnowledgeNode/KnowledgeEdge records.
"""

import json
import logging
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, KnowledgeEdge

logger = logging.getLogger(__name__)

# ── Constants ──

_BLOOM_LEVELS = {
    "remember": 1,
    "understand": 2,
    "apply": 3,
    "analyze": 4,
    "evaluate": 5,
    "create": 6,
}

_EXTRACT_PROMPT = """Analyze this educational content and extract the key concepts being taught.

For each concept, provide:
1. name: A concise concept name (2-5 words, e.g. "Chain Rule", "Supply and Demand")
2. description: One sentence describing what it is
3. prerequisites: List of concept names this concept depends on (from this same content)
4. related: List of concept names that are closely related
5. bloom_level: The Bloom's taxonomy level — one of: remember, understand, apply, analyze, evaluate, create
   - "remember" = recall facts/definitions
   - "understand" = explain concepts
   - "apply" = use in new situations
   - "analyze" = break down, compare
   - "evaluate" = judge, critique
   - "create" = produce new work

Output valid JSON array. Example:
[
  {{"name": "Derivative", "description": "Rate of change of a function", "prerequisites": [], "related": ["Limit"], "bloom_level": "understand"}},
  {{"name": "Chain Rule", "description": "Derivative of composed functions", "prerequisites": ["Derivative"], "related": ["Product Rule"], "bloom_level": "apply"}}
]

Content title: {title}

Content (first 3000 chars):
{content}"""


# ── Concept Extraction ──

async def extract_course_concepts(
    db: AsyncSession,
    course_id: uuid.UUID,
    max_nodes: int = 10,
) -> list[KnowledgeNode]:
    """Extract concept nodes from course content via LLM.

    Idempotent: skips if concepts already exist for this course.
    """
    # Check if concepts already exist
    existing = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeNode)
            .where(KnowledgeNode.course_id == course_id)
        )
    ).scalar() or 0
    if existing > 0:
        logger.info("Concepts already exist for course %s (%d nodes), skipping extraction", course_id, existing)
        result = await db.execute(
            select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
        )
        return list(result.scalars().all())

    # Get content nodes
    from models.content import CourseContentTree
    result = await db.execute(
        select(CourseContentTree).where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.content.isnot(None),
        )
    )
    content_nodes = result.scalars().all()
    eligible = [n for n in content_nodes if n.content and len(n.content) > 200]
    if not eligible:
        return []

    # Combine content from top nodes for extraction
    combined = "\n\n---\n\n".join(
        f"## {n.title}\n{n.content[:1500]}" for n in eligible[:5]
    )

    try:
        from services.llm.router import get_llm_client
        client = get_llm_client("fast")
        prompt = _EXTRACT_PROMPT.format(
            title=eligible[0].title,
            content=combined[:3000],
        )
        raw, _ = await client.extract(
            "You are a curriculum analyst. Output valid JSON arrays only.",
            prompt,
        )

        # Parse JSON
        json_start = raw.find("[")
        json_end = raw.rfind("]") + 1
        if json_start < 0 or json_end <= json_start:
            logger.warning("No JSON array found in concept extraction response")
            return []

        concepts_data = json.loads(raw[json_start:json_end])
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Concept extraction JSON parse failed: %s", e)
        return []
    except (ConnectionError, TimeoutError, RuntimeError) as e:
        logger.exception("Concept extraction LLM call failed")
        return []

    # Create nodes
    nodes: list[KnowledgeNode] = []
    node_by_name: dict[str, KnowledgeNode] = {}

    for item in concepts_data[:max_nodes]:
        name = (item.get("name") or "").strip()
        if not name or len(name) > 200:
            continue

        bloom_raw = (item.get("bloom_level") or "understand").lower()
        bloom_level = _BLOOM_LEVELS.get(bloom_raw, 2)

        node = KnowledgeNode(
            course_id=course_id,
            name=name,
            description=(item.get("description") or "")[:500],
            metadata_={
                "source": "auto_extracted",
                "bloom_level": bloom_level,
                "bloom_label": bloom_raw if bloom_raw in _BLOOM_LEVELS else "understand",
                "prerequisites_raw": item.get("prerequisites", []),
                "related_raw": item.get("related", []),
            },
        )
        db.add(node)
        nodes.append(node)
        node_by_name[name.lower()] = node

    await db.flush()  # Assign IDs

    # Create edges
    for item in concepts_data[:max_nodes]:
        name = (item.get("name") or "").strip().lower()
        source = node_by_name.get(name)
        if not source:
            continue

        for prereq_name in item.get("prerequisites", []):
            target = node_by_name.get(prereq_name.strip().lower())
            if target and target.id != source.id:
                edge = KnowledgeEdge(
                    source_id=source.id,
                    target_id=target.id,
                    relation_type="prerequisite",
                )
                db.add(edge)

        for related_name in item.get("related", []):
            target = node_by_name.get(related_name.strip().lower())
            if target and target.id != source.id:
                edge = KnowledgeEdge(
                    source_id=source.id,
                    target_id=target.id,
                    relation_type="related",
                )
                db.add(edge)

    await db.commit()
    logger.info("Extracted %d concept nodes for course %s", len(nodes), course_id)
    return nodes
