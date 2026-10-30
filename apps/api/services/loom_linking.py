"""Link practice problems and flashcards to LOOM knowledge nodes.

Knowledge points stay coarse: one concept per question (``problem_metadata.
core_concept``) and one ``concept`` per flashcard.  After the course graph
is built, each of those names is resolved to a ``knowledge_nodes`` row —
normalized-name match first, embedding cosine similarity second (same
union-find/embedding helpers the Graphusion fusion stage uses) — and the
resolved id is stored on the asset (``problem_metadata.knowledge_node_id`` /
``card["knowledge_node_id"]``) so attempt handlers can update
``concept_mastery`` without re-resolving.
"""

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode
from services.loom_extraction import _cosine_similarity, _fusion_threshold

logger = logging.getLogger(__name__)

# Looser than concept fusion: we are matching a short label against a node,
# not deciding whether two nodes are the same concept.
LINK_SIMILARITY_MARGIN = 0.10


def normalize_concept_name(name: str) -> str:
    """Case/punctuation-insensitive key for concept name matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(name or "").lower()).strip()


class ConceptResolver:
    """Resolve concept labels to knowledge node ids for one course."""

    def __init__(self, nodes: list[KnowledgeNode]):
        self.nodes = list(nodes)
        self.by_name: dict[str, KnowledgeNode] = {}
        for node in self.nodes:
            self.by_name.setdefault(normalize_concept_name(node.name), node)
        self._node_embeddings: dict[uuid.UUID, list[float]] | None = None
        self._label_cache: dict[str, uuid.UUID | None] = {}

    async def _ensure_node_embeddings(self) -> dict[uuid.UUID, list[float]]:
        if self._node_embeddings is not None:
            return self._node_embeddings
        self._node_embeddings = {}
        try:
            from services.memory.pipeline import generate_embedding
        except ImportError:
            return self._node_embeddings
        for node in self.nodes:
            try:
                emb = await generate_embedding(f"{node.name}: {node.description or ''}")
            except (RuntimeError, OSError):
                emb = None
            if emb:
                self._node_embeddings[node.id] = emb
        return self._node_embeddings

    async def resolve(self, label: str | None) -> uuid.UUID | None:
        key = normalize_concept_name(label or "")
        if not key:
            return None
        if key in self._label_cache:
            return self._label_cache[key]

        node = self.by_name.get(key)
        if node is not None:
            self._label_cache[key] = node.id
            return node.id

        resolved: uuid.UUID | None = None
        node_embeddings = await self._ensure_node_embeddings()
        if node_embeddings:
            try:
                from services.memory.pipeline import generate_embedding
                label_emb = await generate_embedding(str(label))
            except (ImportError, RuntimeError, OSError):
                label_emb = None
            if label_emb:
                threshold = max(0.5, _fusion_threshold() - LINK_SIMILARITY_MARGIN)
                best_sim = threshold
                for node_id, emb in node_embeddings.items():
                    sim = _cosine_similarity(label_emb, emb)
                    if sim > best_sim:
                        best_sim, resolved = sim, node_id
        self._label_cache[key] = resolved
        return resolved


async def load_resolver(db: AsyncSession, course_id: uuid.UUID) -> ConceptResolver:
    result = await db.execute(select(KnowledgeNode).where(KnowledgeNode.course_id == course_id))
    return ConceptResolver(list(result.scalars().all()))


def _first_knowledge_point(problem) -> str | None:
    kp = problem.knowledge_points
    if isinstance(kp, list) and kp:
        return str(kp[0])
    if isinstance(kp, str):
        return kp
    meta = problem.problem_metadata or {}
    return meta.get("core_concept") if isinstance(meta, dict) else None


async def link_course_assets_to_concepts(db: AsyncSession, course_id: uuid.UUID) -> dict[str, int]:
    """Store resolved knowledge node ids on every problem and card of a course.

    Returns counts: ``{"problems": n, "cards": m}``.  Safe to re-run; assets
    already carrying a ``knowledge_node_id`` that still exists are skipped.
    """
    from models.generated_asset import GeneratedAsset
    from models.practice import PracticeProblem

    resolver = await load_resolver(db, course_id)
    if not resolver.nodes:
        return {"problems": 0, "cards": 0}
    valid_ids = {str(n.id) for n in resolver.nodes}

    linked_problems = 0
    result = await db.execute(
        select(PracticeProblem).where(
            PracticeProblem.course_id == course_id,
            PracticeProblem.is_archived == False,  # noqa: E712
        )
    )
    for problem in result.scalars().all():
        meta = dict(problem.problem_metadata or {})
        if meta.get("knowledge_node_id") in valid_ids:
            continue
        node_id = await resolver.resolve(_first_knowledge_point(problem))
        if node_id is None:
            continue
        meta["knowledge_node_id"] = str(node_id)
        problem.problem_metadata = meta
        linked_problems += 1

    linked_cards = 0
    result = await db.execute(
        select(GeneratedAsset).where(
            GeneratedAsset.course_id == course_id,
            GeneratedAsset.asset_type == "flashcards",
            GeneratedAsset.is_archived == False,  # noqa: E712
        )
    )
    for asset in result.scalars().all():
        cards = list((asset.content or {}).get("cards", []))
        changed = False
        for idx, card in enumerate(cards):
            if not isinstance(card, dict) or card.get("knowledge_node_id") in valid_ids:
                continue
            node_id = await resolver.resolve(card.get("concept"))
            if node_id is None:
                continue
            cards[idx] = {**card, "knowledge_node_id": str(node_id)}
            changed = True
            linked_cards += 1
        if changed:
            asset.content = {**asset.content, "cards": cards}

    await db.flush()
    logger.info(
        "Linked %d problems and %d flashcards to concepts for course %s",
        linked_problems, linked_cards, course_id,
    )
    return {"problems": linked_problems, "cards": linked_cards}
