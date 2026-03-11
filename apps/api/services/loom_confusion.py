"""LOOM Confusion Pair Detection.

Analyzes wrong answer data to detect concept confusion pairs.
When a student selects answer X for concept A, and X matches the correct
answer for concept B, this suggests A and B are confused.

Creates `confused_with` edges in the knowledge graph, weighted by frequency.
These edges feed into LECTOR's contrast review sessions.
"""

import logging
import inspect
import uuid
from collections import defaultdict

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import WrongAnswer
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge
from models.practice import PracticeProblem

logger = logging.getLogger(__name__)


async def detect_confusion_pairs(
    db: AsyncSession,
    course_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    min_occurrences: int = 2,
) -> list[dict]:
    """Analyze wrong answers to detect concept confusion pairs.

    Strategy:
    1. Get all wrong answers for the course (optionally filtered by user)
    2. For each wrong answer, check if the user_answer matches the correct
       answer of a different concept's question
    3. Also use error_detail["related_concept"] if available from diagnostics
    4. Create/update `confused_with` edges weighted by frequency

    Returns list of detected confusion pairs.
    """
    # Get wrong answers with their associated knowledge points
    query = (
        select(WrongAnswer)
        .where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.mastered == False,  # noqa: E712
        )
    )
    if user_id:
        query = query.where(WrongAnswer.user_id == user_id)

    result = await db.execute(query)
    wrong_answers = result.scalars().all()

    if not wrong_answers:
        return []

    # Get all concept nodes for this course
    nodes_result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = nodes_result.scalars().all()
    node_by_name = {n.name.lower(): n for n in nodes}

    # Track confusion pairs: (concept_a, concept_b) -> count
    confusion_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)

    for wa in wrong_answers:
        # Method 1: Use error_detail["related_concept"] from diagnostic pair analysis
        if wa.error_detail and wa.error_detail.get("related_concept"):
            related_name = wa.error_detail["related_concept"].lower()
            if related_name in node_by_name:
                related_node = node_by_name[related_name]
                # Find which concept this wrong answer's question belongs to
                source_concepts = wa.knowledge_points or []
                for kp in source_concepts:
                    kp_name = (kp if isinstance(kp, str) else str(kp)).lower()
                    if kp_name in node_by_name:
                        source_node = node_by_name[kp_name]
                        if source_node.id != related_node.id:
                            pair = _ordered_pair(source_node.id, related_node.id)
                            confusion_counts[pair] += 1

        # Method 2: Check if user_answer matches correct answer for another concept
        if wa.knowledge_points and wa.correct_answer and wa.user_answer:
            user_answer_lower = wa.user_answer.strip().lower()
            # This is a heuristic — in MCQ, the wrong answer might be another concept's definition
            for kp in wa.knowledge_points:
                kp_name = (kp if isinstance(kp, str) else str(kp)).lower()
                if kp_name in node_by_name:
                    source_node = node_by_name[kp_name]
                    # Check if any other concept's name/description matches the wrong answer
                    for other_node in nodes:
                        if other_node.id == source_node.id:
                            continue
                        if (
                            other_node.name.lower() in user_answer_lower
                            or user_answer_lower in other_node.name.lower()
                        ):
                            pair = _ordered_pair(source_node.id, other_node.id)
                            confusion_counts[pair] += 1

    # Method 3: Embedding-based similarity between concepts involved in wrong answers
    # Concepts with similar descriptions that appear in wrong-answer sets are likely confused
    wrong_concept_ids = set()
    for wa in wrong_answers:
        for kp in (wa.knowledge_points or []):
            kp_name = (kp if isinstance(kp, str) else str(kp)).lower()
            if kp_name in node_by_name:
                wrong_concept_ids.add(node_by_name[kp_name].id)

    if len(wrong_concept_ids) >= 2:
        try:
            from services.memory.pipeline import generate_embedding
            # Build descriptions for concepts involved in wrong answers
            concept_nodes = [n for n in nodes if n.id in wrong_concept_ids]
            embeddings: dict[uuid.UUID, list[float]] = {}
            for cn in concept_nodes:
                desc = cn.description or cn.name
                emb = await generate_embedding(desc)
                if emb:
                    embeddings[cn.id] = emb

            # Compute pairwise cosine similarity
            emb_ids = list(embeddings.keys())
            for i in range(len(emb_ids)):
                for j in range(i + 1, len(emb_ids)):
                    sim = _cosine_similarity(embeddings[emb_ids[i]], embeddings[emb_ids[j]])
                    if sim > 0.75:
                        pair = _ordered_pair(emb_ids[i], emb_ids[j])
                        confusion_counts[pair] += 1
        except (ImportError, RuntimeError, OSError):
            logger.debug("Embedding-based confusion detection unavailable, skipping")

    # Create/update confused_with edges for pairs meeting threshold
    # Method 1 (error_detail) is high confidence — use min_occurrences=1
    created_pairs = []
    for (node_a_id, node_b_id), count in confusion_counts.items():
        if count < min_occurrences:
            continue

        # Check if edge already exists
        existing = await db.execute(
            select(KnowledgeEdge).where(
                KnowledgeEdge.source_id == node_a_id,
                KnowledgeEdge.target_id == node_b_id,
                KnowledgeEdge.relation_type == "confused_with",
            )
        )
        edge = existing.scalar_one_or_none()

        if edge:
            edge.weight = float(count)
        else:
            edge = KnowledgeEdge(
                source_id=node_a_id,
                target_id=node_b_id,
                relation_type="confused_with",
                weight=float(count),
            )
            add_result = db.add(edge)
            if inspect.isawaitable(add_result):
                await add_result
            # Also add reverse edge (confusion is bidirectional)
            reverse_edge = KnowledgeEdge(
                source_id=node_b_id,
                target_id=node_a_id,
                relation_type="confused_with",
                weight=float(count),
            )
            add_result = db.add(reverse_edge)
            if inspect.isawaitable(add_result):
                await add_result

        node_a = next((n for n in nodes if n.id == node_a_id), None)
        node_b = next((n for n in nodes if n.id == node_b_id), None)
        created_pairs.append({
            "concept_a": node_a.name if node_a else str(node_a_id),
            "concept_b": node_b.name if node_b else str(node_b_id),
            "confusion_count": count,
        })

    if created_pairs:
        await db.flush()
        logger.info(
            "Detected %d confusion pairs for course %s",
            len(created_pairs), course_id,
        )

    return created_pairs


def _ordered_pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """Return a canonical ordered pair to avoid duplicates."""
    return (a, b) if str(a) < str(b) else (b, a)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def get_confused_concepts(
    db: AsyncSession,
    course_id: uuid.UUID,
    concept_name: str | None = None,
) -> list[dict]:
    """Get confused concept pairs for a course or specific concept."""
    nodes_result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = nodes_result.scalars().all()
    node_ids = [n.id for n in nodes]
    node_by_id = {n.id: n for n in nodes}

    query = select(KnowledgeEdge).where(
        KnowledgeEdge.source_id.in_(node_ids),
        KnowledgeEdge.relation_type == "confused_with",
    )

    if concept_name:
        source_node = next(
            (n for n in nodes if n.name.lower() == concept_name.lower()),
            None,
        )
        if not source_node:
            return []
        query = query.where(KnowledgeEdge.source_id == source_node.id)

    result = await db.execute(query)
    edges = result.scalars().all()

    pairs = []
    seen: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for edge in edges:
        pair = _ordered_pair(edge.source_id, edge.target_id)
        if pair in seen:
            continue
        seen.add(pair)
        source = node_by_id.get(edge.source_id)
        target = node_by_id.get(edge.target_id)
        if source and target:
            pairs.append({
                "concept_a": source.name,
                "concept_b": target.name,
                "weight": edge.weight,
            })

    return sorted(pairs, key=lambda p: p["weight"], reverse=True)


# ── Proactive Interference Matrix (LECTOR paper, arXiv 2508.03275) ──

INTERFERENCE_SIMILARITY_THRESHOLD = 0.6
INTERFERENCE_TOP_N = 20


async def compute_interference_matrix(
    db: AsyncSession,
    course_id: uuid.UUID,
    similarity_threshold: float = INTERFERENCE_SIMILARITY_THRESHOLD,
    top_n: int = INTERFERENCE_TOP_N,
) -> list[dict]:
    """Pre-compute pairwise semantic interference between concepts (LECTOR paper).

    Unlike detect_confusion_pairs() which is reactive (runs after wrong answers),
    this function proactively identifies concept pairs at risk of confusion
    based on embedding similarity — BEFORE any student makes a mistake.

    Algorithm:
    1. Compute embeddings for all concept "name: description" strings
    2. Find pairs with cosine similarity > threshold
    3. Create weighted confused_with edges (weight = similarity score)

    These edges feed into LECTOR's Factor 7 (interference boost) for
    review scheduling that avoids consecutive presentation of similar concepts.
    """
    nodes_result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = nodes_result.scalars().all()
    if len(nodes) < 2:
        return []

    # Compute embeddings for all concepts
    try:
        from services.memory.pipeline import generate_embedding
    except ImportError:
        logger.debug("Embedding pipeline unavailable, skipping interference matrix")
        return []

    embeddings: dict[uuid.UUID, list[float]] = {}
    for node in nodes:
        text = f"{node.name}: {node.description or node.name}"
        try:
            emb = await generate_embedding(text)
            if emb:
                embeddings[node.id] = emb
        except (RuntimeError, OSError):
            continue

    if len(embeddings) < 2:
        return []

    # Find high-similarity pairs
    node_list = [n for n in nodes if n.id in embeddings]
    pairs: list[tuple[KnowledgeNode, KnowledgeNode, float]] = []
    for i in range(len(node_list)):
        for j in range(i + 1, len(node_list)):
            sim = _cosine_similarity(
                embeddings[node_list[i].id],
                embeddings[node_list[j].id],
            )
            if sim > similarity_threshold:
                pairs.append((node_list[i], node_list[j], sim))

    # Sort by similarity, take top N
    pairs.sort(key=lambda x: x[2], reverse=True)
    pairs = pairs[:top_n]

    # Create/update confused_with edges
    created: list[dict] = []
    for node_a, node_b, sim in pairs:
        pair_id = _ordered_pair(node_a.id, node_b.id)

        # Check if edge already exists
        existing = await db.execute(
            select(KnowledgeEdge).where(
                KnowledgeEdge.source_id == pair_id[0],
                KnowledgeEdge.target_id == pair_id[1],
                KnowledgeEdge.relation_type == "confused_with",
            )
        )
        edge = existing.scalar_one_or_none()

        if edge:
            edge.weight = max(edge.weight, sim)  # Keep higher weight
        else:
            # Create bidirectional edges (confusion is symmetric)
            db.add(KnowledgeEdge(
                source_id=pair_id[0], target_id=pair_id[1],
                relation_type="confused_with", weight=sim,
            ))
            db.add(KnowledgeEdge(
                source_id=pair_id[1], target_id=pair_id[0],
                relation_type="confused_with", weight=sim,
            ))

        created.append({
            "concept_a": node_a.name,
            "concept_b": node_b.name,
            "interference": round(sim, 3),
        })

    if created:
        await db.flush()
        logger.info(
            "Computed interference matrix: %d pairs for course %s",
            len(created), course_id,
        )

    return created
