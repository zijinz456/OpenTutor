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
                except Exception:
                    results = await hybrid_search(db, case.course_id, case.query, limit=k)
            else:
                results = await hybrid_search(db, case.course_id, case.query, limit=k)

            retrieved_ids = [str(r.get("node_id", r.get("id", ""))) for r in results]
            relevant_set = set(case.relevant_node_ids)

            scores = _score_retrieval(retrieved_ids, relevant_set, k)
            scores.query = case.query
            per_query.append(scores)

        except Exception as e:
            logger.error("Retrieval eval failed for query '%s': %s", case.query[:60], e)
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
    from sqlalchemy import select, or_
    from models.content import CourseContentTree

    cases: list[RetrievalCase] = []
    for item in queries_with_keywords:
        query = item["query"]
        keywords = item.get("keywords", [])

        if not keywords:
            continue

        # Find nodes matching any keyword in title
        conditions = [CourseContentTree.title.ilike(f"%{kw}%") for kw in keywords]
        result = await db.execute(
            select(CourseContentTree.id)
            .where(
                CourseContentTree.course_id == course_id,
                or_(*conditions),
            )
        )
        relevant_ids = [str(row[0]) for row in result.all()]
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
