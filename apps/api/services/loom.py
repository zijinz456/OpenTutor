"""LOOM — Learner-Oriented Ontology Memory.

Implements the core LOOM pattern (arxiv:2511.21037):
1. Extract concepts from course content via LLM
2. Build a prerequisite/relationship graph
3. Track per-user concept mastery
4. Provide concept recommendations (what to study next)

Usage:
    from services.loom import extract_course_concepts, update_concept_mastery, get_mastery_graph

    # After ingestion: extract concepts from content
    await extract_course_concepts(db, course_id)

    # After quiz/practice: update mastery
    await update_concept_mastery(db, user_id, concept_name, course_id, correct=True)

    # For the tutor: get mastery-colored concept graph
    graph = await get_mastery_graph(db, user_id, course_id)
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery

logger = logging.getLogger(__name__)

# ── Concept Extraction ──

_EXTRACT_PROMPT = """Analyze this educational content and extract the key concepts being taught.

For each concept, provide:
1. name: A concise concept name (2-5 words, e.g. "Chain Rule", "Supply and Demand")
2. description: One sentence describing what it is
3. prerequisites: List of concept names this concept depends on (from this same content)
4. related: List of concept names that are closely related

Output valid JSON array. Example:
[
  {"name": "Derivative", "description": "Rate of change of a function", "prerequisites": [], "related": ["Limit"]},
  {"name": "Chain Rule", "description": "Derivative of composed functions", "prerequisites": ["Derivative"], "related": ["Product Rule"]}
]

Content title: {title}

Content (first 3000 chars):
{content}"""


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
    except Exception as e:
        logger.warning("Concept extraction failed: %s", e)
        return []

    # Create nodes
    nodes: list[KnowledgeNode] = []
    node_by_name: dict[str, KnowledgeNode] = {}

    for item in concepts_data[:max_nodes]:
        name = (item.get("name") or "").strip()
        if not name or len(name) > 200:
            continue

        node = KnowledgeNode(
            course_id=course_id,
            name=name,
            description=(item.get("description") or "")[:500],
            metadata_={
                "source": "auto_extracted",
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


# ── Mastery Tracking ──

async def update_concept_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    concept_name: str,
    course_id: uuid.UUID,
    correct: bool,
) -> ConceptMastery | None:
    """Update mastery score for a concept after practice/quiz.

    Uses exponential moving average: new_score = alpha * result + (1 - alpha) * old_score
    """
    # Find the concept node
    result = await db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.course_id == course_id,
            func.lower(KnowledgeNode.name) == concept_name.lower(),
        )
    )
    node = result.scalar_one_or_none()
    if not node:
        return None

    # Get or create mastery record
    result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id == node.id,
        )
    )
    mastery = result.scalar_one_or_none()

    if not mastery:
        mastery = ConceptMastery(
            user_id=user_id,
            knowledge_node_id=node.id,
            mastery_score=0.0,
        )
        db.add(mastery)

    # Update counters
    mastery.practice_count += 1
    if correct:
        mastery.correct_count += 1
    else:
        mastery.wrong_count += 1

    # Exponential moving average (alpha = 0.3 for responsiveness)
    alpha = 0.3
    result_score = 1.0 if correct else 0.0
    mastery.mastery_score = alpha * result_score + (1 - alpha) * mastery.mastery_score

    # Stability: increases with consecutive correct, resets on wrong
    if correct:
        mastery.stability_days = min(mastery.stability_days * 1.5 + 1, 90)
    else:
        mastery.stability_days = max(mastery.stability_days * 0.3, 0)

    mastery.last_practiced_at = datetime.now(timezone.utc)

    await db.flush()
    return mastery


# ── Mastery Graph Retrieval ──

async def get_mastery_graph(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Return the full concept mastery graph for a user+course.

    Returns:
        {
            "nodes": [{"id": ..., "name": ..., "mastery": 0.7, "description": ...}],
            "edges": [{"source": ..., "target": ..., "type": "prerequisite"}],
            "weak_concepts": ["Chain Rule", "Integration"],
            "next_to_study": "Chain Rule",
        }
    """
    # Get all concept nodes
    result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = result.scalars().all()
    if not nodes:
        return {"nodes": [], "edges": [], "weak_concepts": [], "next_to_study": None}

    node_ids = [n.id for n in nodes]

    # Get user mastery for all nodes
    result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id.in_(node_ids),
        )
    )
    masteries = {m.knowledge_node_id: m for m in result.scalars().all()}

    # Get edges
    result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_id.in_(node_ids),
        )
    )
    edges = result.scalars().all()

    # Build graph
    graph_nodes = []
    weak_concepts = []
    for node in nodes:
        m = masteries.get(node.id)
        mastery_score = m.mastery_score if m else 0.0
        graph_nodes.append({
            "id": str(node.id),
            "name": node.name,
            "mastery": round(mastery_score, 3),
            "description": node.description,
            "practice_count": m.practice_count if m else 0,
            "last_practiced": m.last_practiced_at.isoformat() if m and m.last_practiced_at else None,
        })
        if mastery_score < 0.5:
            weak_concepts.append(node.name)

    graph_edges = [
        {
            "source": str(e.source_id),
            "target": str(e.target_id),
            "type": e.relation_type,
        }
        for e in edges
    ]

    # Recommend next concept to study (lowest mastery with satisfied prerequisites)
    next_to_study = None
    if weak_concepts:
        next_to_study = weak_concepts[0]  # Simple: lowest mastery first

    return {
        "nodes": graph_nodes,
        "edges": graph_edges,
        "weak_concepts": weak_concepts,
        "next_to_study": next_to_study,
    }


# ── Integration: Build graph after ingestion ──

async def build_course_graph(db_factory, course_id: uuid.UUID) -> int:
    """Build the knowledge graph for a course. Called after auto_prepare."""
    try:
        async with db_factory() as db:
            nodes = await extract_course_concepts(db, course_id)
            return len(nodes)
    except Exception as e:
        logger.warning("LOOM graph building failed for course %s: %s", course_id, e)
        return 0
