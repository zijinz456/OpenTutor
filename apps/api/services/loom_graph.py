"""LOOM graph — knowledge graph queries, learning paths, and cross-course linking.

Provides mastery graph retrieval, prerequisite gap detection, topological
learning path generation, and cross-course concept linking.
"""

import logging
import uuid
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery

logger = logging.getLogger(__name__)


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

    # Build graph with time-decayed mastery (FSRS retrievability)
    from services.spaced_repetition.fsrs import _retrievability

    now = datetime.now(timezone.utc)
    graph_nodes = []
    weak_concepts = []
    for node in nodes:
        m = masteries.get(node.id)
        raw_mastery = m.mastery_score if m else 0.0
        meta = node.metadata_ or {}

        # Apply FSRS retrievability decay: mastery fades over time
        if m and m.last_practiced_at and m.stability_days and m.stability_days > 0:
            last = m.last_practiced_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            elapsed = (now - last).total_seconds() / 86400
            retrievability = _retrievability(elapsed, m.stability_days)
            effective_mastery = raw_mastery * retrievability
        else:
            retrievability = 1.0 if raw_mastery > 0 else 0.0
            effective_mastery = raw_mastery

        graph_nodes.append({
            "id": str(node.id),
            "name": node.name,
            "mastery": round(effective_mastery, 3),
            "raw_mastery": round(raw_mastery, 3),
            "retrievability": round(retrievability, 3),
            "description": node.description,
            "bloom_level": meta.get("bloom_level", 2),
            "bloom_label": meta.get("bloom_label", "understand"),
            "practice_count": m.practice_count if m else 0,
            "last_practiced": m.last_practiced_at.isoformat() if m and m.last_practiced_at else None,
            "next_review_at": m.next_review_at.isoformat() if m and m.next_review_at else None,
            "stability_days": round(m.stability_days, 1) if m else 0.0,
        })
        if effective_mastery < 0.5:
            weak_concepts.append(node.name)

    graph_edges = [
        {
            "source": str(e.source_id),
            "target": str(e.target_id),
            "type": e.relation_type,
        }
        for e in edges
    ]

    # Recommend next concept via topological sort (prerequisite-respecting order)
    learning_path = await generate_learning_path(db, course_id, user_id)
    next_to_study = learning_path[0]["name"] if learning_path else (
        weak_concepts[0] if weak_concepts else None
    )

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


async def check_prerequisites_satisfied(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    concept_names: list[str],
    threshold: float = 0.4,
) -> tuple[bool, list[dict]]:
    """Check whether prerequisites for the given concepts are satisfied.

    Returns ``(all_satisfied, gaps)`` where *gaps* is a list of
    ``{"concept", "concept_id", "mastery", "gap_severity", "blocks"}``
    — *blocks* lists the downstream concepts that are gated by this gap.
    """
    gaps = await check_prerequisite_gaps(
        db, user_id, course_id,
        failed_concept_names=concept_names,
        mastery_threshold=threshold,
    )
    return (len(gaps) == 0, gaps)


# ── Learning Path Generation ──

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
    """Build the knowledge graph for a course. Called after auto_prepare.

    Retries extraction once if the first attempt yields 0 nodes (transient LLM failure).
    """
    try:
        async with db_factory() as db:
            from services.loom_extraction import extract_course_concepts
            nodes = await extract_course_concepts(db, course_id)
            if not nodes:
                # Single retry — transient LLM failures are common
                import asyncio
                await asyncio.sleep(2)
                nodes = await extract_course_concepts(db, course_id)
            # Link same-name concepts across courses
            await link_cross_course_concepts(db, course_id)
            # Compute proactive interference matrix (LECTOR paper, arXiv 2508.03275)
            try:
                from services.loom_confusion import compute_interference_matrix
                await compute_interference_matrix(db, course_id)
            except (ImportError, RuntimeError, OSError):
                logger.debug("Interference matrix computation skipped (embedding unavailable)")
            return len(nodes)
    except (ConnectionError, TimeoutError, RuntimeError, ValueError, OSError) as e:
        logger.exception("LOOM graph building failed for course %s: %s", course_id, e)
        return 0


async def link_cross_course_concepts(
    db: AsyncSession,
    course_id: uuid.UUID,
) -> int:
    """Find and link identical concepts across different courses.

    When a concept like "eigenvalue" appears in both Linear Algebra and
    Machine Learning, create a `reinforces` edge so mastery in one course
    can propagate partial credit to the other via FIRe.
    """
    # Get concepts for the new course
    result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    new_nodes = result.scalars().all()
    if not new_nodes:
        return 0

    # Get concepts from ALL other courses
    result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id != course_id)
    )
    other_nodes = result.scalars().all()
    if not other_nodes:
        return 0

    # Build name -> nodes map for other courses
    other_by_name: dict[str, list[KnowledgeNode]] = {}
    for n in other_nodes:
        other_by_name.setdefault(n.name.lower(), []).append(n)

    linked = 0
    for node in new_nodes:
        matches = other_by_name.get(node.name.lower(), [])
        for other in matches:
            # Check if edge already exists
            existing = await db.execute(
                select(KnowledgeEdge).where(
                    KnowledgeEdge.source_id == node.id,
                    KnowledgeEdge.target_id == other.id,
                    KnowledgeEdge.relation_type == "reinforces",
                )
            )
            if existing.scalar_one_or_none():
                continue

            # Create bidirectional reinforces edges
            db.add(KnowledgeEdge(
                source_id=node.id,
                target_id=other.id,
                relation_type="reinforces",
                weight=1.0,
            ))
            db.add(KnowledgeEdge(
                source_id=other.id,
                target_id=node.id,
                relation_type="reinforces",
                weight=1.0,
            ))
            linked += 1

    if linked:
        await db.flush()
        logger.info(
            "Linked %d cross-course concept pairs for course %s",
            linked, course_id,
        )

    return linked
