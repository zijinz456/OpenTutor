"""LOOM extraction — concept extraction from course content via LLM.

Extracts concepts, prerequisites, and relationships from educational content
and stores them as KnowledgeNode/KnowledgeEdge records.

Academic foundations:
- Graphusion (arXiv 2407.10794): multi-chunk extraction + embedding-based fusion/dedup
  Instead of combining all content into one blob, we extract per-chunk then fuse
  duplicates using embedding cosine similarity (threshold > 0.85).
"""

import json
import logging
import math
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

FUSION_SIMILARITY_THRESHOLD = 0.85  # Graphusion: merge concepts above this cosine similarity

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


# ── Per-Chunk Extraction ──

def _parse_concepts_json(raw: str) -> list[dict]:
    """Parse a JSON array of concepts from LLM output."""
    json_start = raw.find("[")
    json_end = raw.rfind("]") + 1
    if json_start < 0 or json_end <= json_start:
        return []
    return json.loads(raw[json_start:json_end])


async def _extract_from_chunk(client, title: str, content: str) -> list[dict]:
    """Extract concepts from a single content chunk via LLM.

    Part of the Graphusion-inspired multi-chunk extraction pipeline.
    Each chunk is processed independently to capture chunk-specific concepts.
    """
    prompt = _EXTRACT_PROMPT.format(title=title, content=content[:3000])
    try:
        raw, _ = await client.extract(
            "You are a curriculum analyst. Output valid JSON arrays only.",
            prompt,
        )
        return _parse_concepts_json(raw)
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Chunk extraction JSON parse failed for '%s': %s", title, e)
        return []
    except (ConnectionError, TimeoutError, RuntimeError) as e:
        logger.warning("Chunk extraction LLM call failed for '%s': %s", title, e)
        return []


# ── Graphusion Fusion/Dedup ──

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_merge_groups(
    concepts: list[dict],
    embeddings: dict[int, list[float]],
    threshold: float = FUSION_SIMILARITY_THRESHOLD,
) -> list[list[int]]:
    """Find groups of similar concepts using union-find on embedding similarity.

    Based on Graphusion paper's fusion stage: concepts with cosine similarity
    above threshold are merged into a single canonical concept.
    """
    n = len(concepts)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    emb_indices = sorted(embeddings.keys())
    for i in range(len(emb_indices)):
        for j in range(i + 1, len(emb_indices)):
            idx_a, idx_b = emb_indices[i], emb_indices[j]
            sim = _cosine_similarity(embeddings[idx_a], embeddings[idx_b])
            if sim > threshold:
                union(idx_a, idx_b)

    # Collect groups (only groups with 2+ members)
    from collections import defaultdict
    groups: dict[int, list[int]] = defaultdict(list)
    for idx in emb_indices:
        groups[find(idx)].append(idx)

    return [g for g in groups.values() if len(g) > 1]


def _merge_concept_group(group: list[dict]) -> dict:
    """Merge a group of duplicate concepts into one canonical concept.

    Graphusion rule: "Keep the more specific term. Only one relation between two concepts."
    We keep the concept with the longest description (most informative) and
    union all prerequisites/related from the group.
    """
    best = max(group, key=lambda c: len(c.get("description", "")))
    merged = dict(best)  # Copy to avoid mutating original

    all_prereqs: set[str] = set()
    all_related: set[str] = set()
    for c in group:
        all_prereqs.update(c.get("prerequisites", []))
        all_related.update(c.get("related", []))

    # Remove self-references
    merged_name = merged.get("name", "")
    merged["prerequisites"] = [p for p in all_prereqs if p != merged_name]
    merged["related"] = [r for r in all_related if r != merged_name]
    return merged


async def _fuse_concepts(concepts: list[dict]) -> list[dict]:
    """Merge duplicate concepts using embedding similarity (Graphusion fusion stage).

    Pipeline:
    1. Generate embeddings for each concept's "name: description"
    2. Find merge groups via cosine similarity > threshold (union-find)
    3. Merge each group: keep most descriptive name, union relationships
    4. Return deduplicated concept list

    Falls back to unmodified list if embeddings unavailable.
    """
    if len(concepts) <= 1:
        return concepts

    # Step 1: Build embeddings
    try:
        from services.memory.pipeline import generate_embedding
    except ImportError:
        logger.debug("Embedding pipeline unavailable, skipping concept fusion")
        return concepts

    embeddings: dict[int, list[float]] = {}
    for i, c in enumerate(concepts):
        text = f"{c.get('name', '')}: {c.get('description', '')}"
        try:
            emb = await generate_embedding(text)
            if emb:
                embeddings[i] = emb
        except (RuntimeError, OSError):
            continue

    if len(embeddings) < 2:
        return concepts

    # Step 2: Find merge groups
    merge_groups = _find_merge_groups(concepts, embeddings)

    if not merge_groups:
        return concepts  # No duplicates found

    # Step 3: Merge each group
    fused: list[dict] = []
    merged_indices: set[int] = set()
    for group_indices in merge_groups:
        group_concepts = [concepts[i] for i in group_indices]
        merged = _merge_concept_group(group_concepts)
        fused.append(merged)
        merged_indices.update(group_indices)
        logger.info(
            "Fused %d duplicate concepts into '%s': %s",
            len(group_indices), merged["name"],
            [concepts[i].get("name") for i in group_indices],
        )

    # Add non-merged concepts
    for i, c in enumerate(concepts):
        if i not in merged_indices:
            fused.append(c)

    logger.info("Concept fusion: %d → %d concepts", len(concepts), len(fused))
    return fused


# ── Main Extraction ──

async def extract_course_concepts(
    db: AsyncSession,
    course_id: uuid.UUID,
    max_nodes: int = 10,
) -> list[KnowledgeNode]:
    """Extract concept nodes from course content via LLM.

    Graphusion-inspired pipeline:
    1. Per-chunk extraction: extract concepts from each content node separately
    2. Embedding-based fusion: merge duplicate concepts across chunks
    3. Node/edge creation: store deduplicated concepts in the knowledge graph

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

    # Phase 1: Per-chunk extraction (Graphusion multi-chunk approach)
    try:
        from services.llm.router import get_llm_client
        client = get_llm_client("fast")
    except (ImportError, RuntimeError) as e:
        logger.error("LLM client unavailable for concept extraction: %s", e)
        return []

    all_concepts: list[dict] = []
    for content_node in eligible[:5]:
        chunk_concepts = await _extract_from_chunk(
            client, content_node.title, content_node.content,
        )
        all_concepts.extend(chunk_concepts)

    if not all_concepts:
        # Fallback: try combined extraction (original approach)
        combined = "\n\n---\n\n".join(
            f"## {n.title}\n{n.content[:1500]}" for n in eligible[:5]
        )
        all_concepts = await _extract_from_chunk(client, eligible[0].title, combined)

    if not all_concepts:
        logger.error("Concept extraction returned 0 concepts for course %s", course_id)
        return []

    # Phase 2: Graphusion fusion — deduplicate similar concepts across chunks
    concepts_data = await _fuse_concepts(all_concepts)

    # Phase 3: Create nodes and edges from fused concepts
    nodes: list[KnowledgeNode] = []
    node_by_name: dict[str, KnowledgeNode] = {}

    for item in concepts_data[:max_nodes]:
        name = (item.get("name") or "").strip()
        if not name or len(name) > 200:
            continue

        # Skip if we already have a node with this name (case-insensitive dedup)
        if name.lower() in node_by_name:
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

    # Link concepts to their source content nodes
    for node in nodes:
        for content_node in eligible[:5]:
            if node.name.lower() in (content_node.content or "").lower():
                node.content_node_id = content_node.id
                break

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
    logger.info("Extracted %d concept nodes for course %s (after fusion)", len(nodes), course_id)
    return nodes
