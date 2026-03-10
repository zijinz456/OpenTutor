"""Evaluation: RAG retrieval quality (recall, precision, MRR).

Measures how well the hybrid search + rag-fusion pipeline surfaces
relevant content for known queries.  Uses a golden test set where
each query has manually tagged relevant content node IDs.

Metrics:
- Recall@K: fraction of relevant docs found in top K results
- Precision@K: fraction of top K results that are relevant
- MRR (Mean Reciprocal Rank): 1/rank of first relevant result
- NDCG@K: normalised discounted cumulative gain (order-aware)

Reference: BEIR benchmark methodology (Thakur et al., 2021)
"""

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@dataclass
class RetrievalCase:
    """A single retrieval evaluation case."""
    query: str
    course_id: uuid.UUID
    relevant_node_ids: list[str]  # Ground truth: IDs of relevant content nodes
    description: str = ""


@dataclass
class RetrievalScores:
    """Scores for a single retrieval case."""
    query: str
    recall_at_k: float
    precision_at_k: float
    reciprocal_rank: float  # 1/rank of first relevant hit (0 if none)
    ndcg_at_k: float
    retrieved_ids: list[str]
    relevant_found: list[str]
    k: int


@dataclass
class RetrievalEvalResult:
    """Aggregate retrieval evaluation results."""
    total: int
    avg_recall: float
    avg_precision: float
    mrr: float  # Mean Reciprocal Rank
    avg_ndcg: float
    per_query: list[RetrievalScores]


@dataclass
class _CourseNodeSnapshot:
    id: str
    title: str
    content: str | None
    parent_id: str | None


def _dcg(relevance_flags: list[bool], k: int) -> float:
    """Discounted Cumulative Gain for binary relevance."""
    dcg = 0.0
    for i, rel in enumerate(relevance_flags[:k]):
        if rel:
            dcg += 1.0 / (i + 2)  # log2(i+2) approximated by (i+2) for simplicity
    return dcg


def _ndcg(relevance_flags: list[bool], num_relevant: int, k: int) -> float:
    """Normalised DCG: DCG / ideal DCG."""
    actual = _dcg(relevance_flags, k)
    ideal_flags = [True] * min(num_relevant, k) + [False] * max(0, k - num_relevant)
    ideal = _dcg(ideal_flags, k)
    return actual / ideal if ideal > 0 else 0.0


def _score_retrieval(
    retrieved_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> RetrievalScores:
    """Compute retrieval metrics for a single query."""
    top_k = retrieved_ids[:k]
    relevance_flags = [rid in relevant_ids for rid in top_k]

    relevant_found = [rid for rid in top_k if rid in relevant_ids]
    recall = len(relevant_found) / len(relevant_ids) if relevant_ids else 0.0
    precision = len(relevant_found) / k if k > 0 else 0.0

    # Reciprocal rank: 1/position of first relevant result
    rr = 0.0
    for i, is_rel in enumerate(relevance_flags):
        if is_rel:
            rr = 1.0 / (i + 1)
            break

    ndcg = _ndcg(relevance_flags, len(relevant_ids), k)

    return RetrievalScores(
        query="",  # filled by caller
        recall_at_k=recall,
        precision_at_k=precision,
        reciprocal_rank=rr,
        ndcg_at_k=ndcg,
        retrieved_ids=top_k,
        relevant_found=relevant_found,
        k=k,
    )


def _keyword_overlap_score(node: _CourseNodeSnapshot, keywords: list[str]) -> tuple[int, int, int]:
    """Score a node by keyword overlap, favouring title hits over body hits."""
    title = (node.title or "").lower()
    content = (node.content or "").lower()
    title_hits = sum(1 for kw in keywords if kw in title)
    content_hits = sum(1 for kw in keywords if kw in content)
    weighted = (title_hits * 3) + content_hits
    return weighted, title_hits, content_hits


def _build_relevant_ids_from_keywords(
    nodes: list[_CourseNodeSnapshot],
    keywords: list[str],
) -> list[str]:
    """Pick benchmark ground-truth ids that are actually retrievable content nodes.

    The previous approach only matched keywords against titles, which often picked
    section containers with no content. Those nodes are not returned by the search
    pipeline, so the benchmark could fail even when retrieval was behaving well.
    """
    normalized = [kw.strip().lower() for kw in keywords if kw and kw.strip()]
    if not normalized or not nodes:
        return []

    by_parent: dict[str | None, list[_CourseNodeSnapshot]] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    scored: list[tuple[_CourseNodeSnapshot, int, int, int]] = []
    for node in nodes:
        weighted, title_hits, content_hits = _keyword_overlap_score(node, normalized)
        if weighted > 0:
            scored.append((node, weighted, title_hits, content_hits))

    if not scored:
        return []

    best_score = max(weighted for _, weighted, _, _ in scored)
    direct_ids: list[str] = []
    container_candidates: list[_CourseNodeSnapshot] = []

    for node, weighted, _title_hits, _content_hits in scored:
        if weighted != best_score:
            continue
        if node.content:
            direct_ids.append(node.id)
        else:
            container_candidates.append(node)

    if direct_ids:
        return direct_ids

    descendant_ids: list[str] = []
    queue = [node.id for node in container_candidates]
    seen: set[str] = set(queue)
    best_descendant_score = 0

    while queue:
        parent_id = queue.pop(0)
        for child in by_parent.get(parent_id, []):
            if child.id in seen:
                continue
            seen.add(child.id)
            weighted, _title_hits, _content_hits = _keyword_overlap_score(child, normalized)
            if child.content and weighted > 0:
                if weighted > best_descendant_score:
                    best_descendant_score = weighted
                    descendant_ids = [child.id]
                elif weighted == best_descendant_score:
                    descendant_ids.append(child.id)
            queue.append(child.id)

    if descendant_ids:
        return descendant_ids

    fallback_score = max(
        weighted for node, weighted, _title_hits, _content_hits in scored if node.content
    ) if any(node.content for node, *_rest in scored) else 0
    if fallback_score <= 0:
        return []
    return [
        node.id
        for node, weighted, _title_hits, _content_hits in scored
        if node.content and weighted == fallback_score
    ]


async def eval_retrieval(
    db: AsyncSession,
    cases: list[RetrievalCase],
    k: int = 5,
    use_rag_fusion: bool = True,
) -> RetrievalEvalResult:
    """Evaluate retrieval quality on a set of golden test cases.

    Runs hybrid_search (or rag_fusion_search) for each case and computes
    recall, precision, MRR, and NDCG against known relevant node IDs.
    """
    from services.search.hybrid import hybrid_search

    per_query: list[RetrievalScores] = []

    for case in cases:
        try:
            if use_rag_fusion:
                try:
                    from services.search.rag_fusion import rag_fusion_search
                    results = await rag_fusion_search(db, case.course_id, case.query, limit=k)
                except (ValueError, RuntimeError, OSError) as _fuse_err:
                    logger.warning("rag_fusion_search failed for query '%s', falling back to hybrid_search", case.query[:60])
                    results = await hybrid_search(db, case.course_id, case.query, limit=k)
            else:
                results = await hybrid_search(db, case.course_id, case.query, limit=k)

            retrieved_ids = [str(r.get("node_id", r.get("id", ""))) for r in results]
            relevant_set = set(case.relevant_node_ids)

            scores = _score_retrieval(retrieved_ids, relevant_set, k)
            scores.query = case.query
            per_query.append(scores)

        except (ValueError, RuntimeError, OSError) as e:
            logger.exception("Retrieval eval failed for query '%s'", case.query[:60])
            per_query.append(RetrievalScores(
                query=case.query,
                recall_at_k=0.0,
                precision_at_k=0.0,
                reciprocal_rank=0.0,
                ndcg_at_k=0.0,
                retrieved_ids=[],
                relevant_found=[],
                k=k,
            ))

    total = len(per_query)
    valid = [s for s in per_query if s.retrieved_ids]

    return RetrievalEvalResult(
        total=total,
        avg_recall=sum(s.recall_at_k for s in valid) / len(valid) if valid else 0.0,
        avg_precision=sum(s.precision_at_k for s in valid) / len(valid) if valid else 0.0,
        mrr=sum(s.reciprocal_rank for s in valid) / len(valid) if valid else 0.0,
        avg_ndcg=sum(s.ndcg_at_k for s in valid) / len(valid) if valid else 0.0,
        per_query=per_query,
    )


async def eval_retrieval_from_course(
    db: AsyncSession,
    course_id: uuid.UUID,
    queries_with_keywords: list[dict],
    k: int = 5,
) -> RetrievalEvalResult:
    """Auto-build golden set from course content nodes matching keywords.

    For each query, finds content nodes whose title contains any of the
    provided keywords and uses those as the ground truth relevant set.
    Useful when manually curating node IDs is impractical.

    queries_with_keywords: [{"query": "...", "keywords": ["term1", "term2"]}]
    """
    from sqlalchemy import select
    from models.content import CourseContentTree

    result = await db.execute(
        select(
            CourseContentTree.id,
            CourseContentTree.title,
            CourseContentTree.content,
            CourseContentTree.parent_id,
        ).where(CourseContentTree.course_id == course_id)
    )
    nodes = [
        _CourseNodeSnapshot(
            id=str(row.id),
            title=row.title or "",
            content=row.content,
            parent_id=str(row.parent_id) if row.parent_id else None,
        )
        for row in result.all()
    ]

    cases: list[RetrievalCase] = []
    for item in queries_with_keywords:
        query = item["query"]
        keywords = item.get("keywords", [])

        if not keywords:
            continue

        relevant_ids = _build_relevant_ids_from_keywords(nodes, keywords)
        if relevant_ids:
            cases.append(RetrievalCase(
                query=query,
                course_id=course_id,
                relevant_node_ids=relevant_ids,
                description=f"Auto-built from keywords: {keywords}",
            ))

    if not cases:
        return RetrievalEvalResult(
            total=0, avg_recall=0, avg_precision=0, mrr=0, avg_ndcg=0, per_query=[],
        )

    return await eval_retrieval(db, cases, k=k)
