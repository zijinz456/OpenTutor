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

    # FSRS-based stability and scheduling
    from services.spaced_repetition.fsrs import FSRSCard, review_card as fsrs_review

    fsrs_card = FSRSCard(
        difficulty=5.0,
        stability=mastery.stability_days if mastery.stability_days > 0 else 0.0,
        reps=mastery.practice_count - 1,  # -1 because we already incremented
        lapses=mastery.wrong_count,
        last_review=mastery.last_practiced_at,
        state="review" if mastery.practice_count > 1 else "new",
    )

    # Map correct/incorrect to FSRS ratings
    if correct:
        rating = 3  # Good
    else:
        rating = 1  # Again

    now = datetime.now(timezone.utc)
    updated_card, _ = fsrs_review(fsrs_card, rating, now)
    mastery.stability_days = updated_card.stability
    mastery.last_practiced_at = now
    mastery.next_review_at = updated_card.due  # Now properly set via FSRS scheduling

    # FIRe: Fractional Implicit Repetitions — propagate partial credit to prerequisites
    await _fire_propagate(db, user_id, node.id, course_id, correct)

    await db.flush()
    return mastery


# ── FIRe: Fractional Implicit Repetitions ──

async def _fire_propagate(
    db: AsyncSession,
    user_id: uuid.UUID,
    practiced_node_id: uuid.UUID,
    course_id: uuid.UUID,
    correct: bool,
    max_depth: int = 3,
) -> None:
    """Propagate fractional review credit to prerequisite concepts.

    When a student practices concept A, prerequisite concepts B, C, ...
    receive implicit review credit proportional to 1/(depth+1).
    Reference: "Fractional Implicit Repetitions in Knowledge Graphs" (2024)
    """
    if not correct:
        return  # Only propagate on successful recall

    # Get prerequisite edges from practiced node
    edges_result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_id == practiced_node_id,
            KnowledgeEdge.relation_type == "prerequisite",
        )
    )
    prereq_edges = edges_result.scalars().all()
    if not prereq_edges:
        return

    visited: set[uuid.UUID] = {practiced_node_id}
    queue: list[tuple[uuid.UUID, int]] = [(e.target_id, 1) for e in prereq_edges]

    while queue:
        prereq_id, depth = queue.pop(0)
        if prereq_id in visited or depth > max_depth:
            continue
        visited.add(prereq_id)

        # Apply fractional credit
        fraction = 1.0 / (depth + 1)

        mastery_result = await db.execute(
            select(ConceptMastery).where(
                ConceptMastery.user_id == user_id,
                ConceptMastery.knowledge_node_id == prereq_id,
            )
        )
        prereq_mastery = mastery_result.scalar_one_or_none()
        if prereq_mastery:
            # Fractional boost: small mastery increase without full practice credit
            boost = fraction * 0.05  # 5% * fraction
            prereq_mastery.mastery_score = min(1.0, prereq_mastery.mastery_score + boost)

        # Continue walking up the prerequisite chain
        deeper_edges = await db.execute(
            select(KnowledgeEdge).where(
                KnowledgeEdge.source_id == prereq_id,
                KnowledgeEdge.relation_type == "prerequisite",
            )
        )
        for edge in deeper_edges.scalars().all():
            if edge.target_id not in visited:
                queue.append((edge.target_id, depth + 1))


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
        meta = node.metadata_ or {}
        graph_nodes.append({
            "id": str(node.id),
            "name": node.name,
            "mastery": round(mastery_score, 3),
            "description": node.description,
            "bloom_level": meta.get("bloom_level", 2),
            "bloom_label": meta.get("bloom_label", "understand"),
            "practice_count": m.practice_count if m else 0,
            "last_practiced": m.last_practiced_at.isoformat() if m and m.last_practiced_at else None,
            "next_review_at": m.next_review_at.isoformat() if m and m.next_review_at else None,
            "stability_days": round(m.stability_days, 1) if m else 0.0,
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


# ── Prerequisite Gap Detection ──

async def check_prerequisite_gaps(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    failed_concept_names: list[str] | None = None,
    mastery_threshold: float = 0.4,
) -> list[dict]:
    """Walk prerequisite edges of failed concepts and find unmastered parents.

    Returns list of ``{"concept": str, "concept_id": str, "mastery": float, "gap_severity": float}``
    sorted by gap_severity descending.
    """
    # Get all nodes and edges for this course
    nodes_result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = nodes_result.scalars().all()
    if not nodes:
        return []

    node_by_id = {n.id: n for n in nodes}
    node_by_name = {n.name.lower(): n for n in nodes}
    node_ids = [n.id for n in nodes]

    # Get prerequisite edges (source depends on target)
    edges_result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_id.in_(node_ids),
            KnowledgeEdge.relation_type == "prerequisite",
        )
    )
    edges = edges_result.scalars().all()

    # Build prerequisite map: concept -> list of prerequisite concept IDs
    prereq_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for edge in edges:
        prereq_map.setdefault(edge.source_id, []).append(edge.target_id)

    # Get user mastery for all nodes
    mastery_result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id.in_(node_ids),
        )
    )
    masteries = {m.knowledge_node_id: m.mastery_score for m in mastery_result.scalars().all()}

    # Determine which concepts to check
    if failed_concept_names:
        target_ids = [
            node_by_name[name.lower()].id
            for name in failed_concept_names
            if name.lower() in node_by_name
        ]
    else:
        # Check all concepts with low mastery
        target_ids = [n.id for n in nodes if masteries.get(n.id, 0.0) < 0.5]

    # Walk prerequisite edges and collect gaps
    gaps: dict[uuid.UUID, dict] = {}
    visited: set[uuid.UUID] = set()

    def _walk(node_id: uuid.UUID) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        for prereq_id in prereq_map.get(node_id, []):
            prereq_mastery = masteries.get(prereq_id, 0.0)
            if prereq_mastery < mastery_threshold and prereq_id in node_by_id:
                prereq_node = node_by_id[prereq_id]
                gaps[prereq_id] = {
                    "concept": prereq_node.name,
                    "concept_id": str(prereq_id),
                    "mastery": round(prereq_mastery, 3),
                    "gap_severity": round(1.0 - prereq_mastery, 3),
                }
            _walk(prereq_id)

    for tid in target_ids:
        _walk(tid)

    return sorted(gaps.values(), key=lambda g: g["gap_severity"], reverse=True)


async def generate_learning_path(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[dict]:
    """Topological sort (Kahn's algorithm) over prerequisite edges, filtered to unmastered concepts.

    Returns ordered list of ``{"id": str, "name": str, "mastery": float}``
    representing the recommended study order.
    """
    nodes_result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = nodes_result.scalars().all()
    if not nodes:
        return []

    node_by_id = {n.id: n for n in nodes}
    node_ids = [n.id for n in nodes]

    # Get user mastery
    mastery_result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id.in_(node_ids),
        )
    )
    masteries = {m.knowledge_node_id: m.mastery_score for m in mastery_result.scalars().all()}

    # Filter to unmastered concepts (mastery < 0.8)
    unmastered_ids = {n.id for n in nodes if masteries.get(n.id, 0.0) < 0.8}
    if not unmastered_ids:
        return []

    # Get prerequisite edges among unmastered concepts
    edges_result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_id.in_(list(unmastered_ids)),
            KnowledgeEdge.relation_type == "prerequisite",
        )
    )
    edges = edges_result.scalars().all()

    # Kahn's algorithm: source depends on target, so target should come first
    in_degree: dict[uuid.UUID, int] = {nid: 0 for nid in unmastered_ids}
    # Reverse edges: if A->B is "prerequisite", B must come before A
    adj: dict[uuid.UUID, list[uuid.UUID]] = {nid: [] for nid in unmastered_ids}
    for edge in edges:
        if edge.target_id in unmastered_ids and edge.source_id in unmastered_ids:
            adj[edge.target_id].append(edge.source_id)
            in_degree[edge.source_id] = in_degree.get(edge.source_id, 0) + 1

    from collections import deque
    queue: deque[uuid.UUID] = deque()
    for nid in unmastered_ids:
        if in_degree.get(nid, 0) == 0:
            queue.append(nid)

    # Sort queue by Bloom level (lower first), then mastery (lowest first)
    def _sort_key(nid: uuid.UUID) -> tuple:
        node = node_by_id[nid]
        bloom = (node.metadata_ or {}).get("bloom_level", 2)
        return (bloom, masteries.get(nid, 0.0))

    queue = deque(sorted(queue, key=_sort_key))

    result: list[dict] = []
    while queue:
        nid = queue.popleft()
        node = node_by_id[nid]
        result.append({
            "id": str(nid),
            "name": node.name,
            "mastery": round(masteries.get(nid, 0.0), 3),
        })
        for neighbor in adj.get(nid, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        # Re-sort new entries by Bloom level then mastery
        queue = deque(sorted(queue, key=_sort_key))

    # Append any remaining (cycle) nodes sorted by mastery
    remaining = unmastered_ids - {uuid.UUID(r["id"]) for r in result}
    for nid in sorted(remaining, key=lambda nid: masteries.get(nid, 0.0)):
        node = node_by_id[nid]
        result.append({
            "id": str(nid),
            "name": node.name,
            "mastery": round(masteries.get(nid, 0.0), 3),
        })

    return result


# ── Integration: Build graph after ingestion ──

async def build_course_graph(db_factory, course_id: uuid.UUID) -> int:
    """Build the knowledge graph for a course. Called after auto_prepare."""
    try:
        async with db_factory() as db:
            nodes = await extract_course_concepts(db, course_id)
            return len(nodes)
    except Exception as e:
        logger.exception("LOOM graph building failed for course %s", course_id)
        return 0
