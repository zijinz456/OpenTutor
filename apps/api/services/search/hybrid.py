"""Hybrid search with RRF fusion ranking.

Combines PageIndex tree search + pgvector similarity search using
Reciprocal Rank Fusion: score = 1/(k + rank), k=60 (standard).

Reference:
- spec Phase 1: RRF fusion ranking
- PageIndex: tree-based reasoning search (98.7% accuracy on FinanceBench)
- pgvector: cosine distance for semantic similarity
"""

import uuid
import logging

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree

logger = logging.getLogger(__name__)

# RRF constant (standard value from literature)
RRF_K = 60


def rrf_score(rank: int) -> float:
    """Reciprocal Rank Fusion score: 1/(k + rank)."""
    return 1.0 / (RRF_K + rank)


async def keyword_search(
    db: AsyncSession,
    course_id: uuid.UUID,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Keyword search over content tree (upgraded from ILIKE to multi-term).

    Phase 1: Splits query into terms, scores by term hit count.
    """
    terms = [t.strip() for t in query.split() if len(t.strip()) >= 2]
    if not terms:
        terms = [query[:100]]

    # Fetch candidates matching any term
    conditions = [CourseContentTree.content.ilike(f"%{t}%") for t in terms[:5]]
    from sqlalchemy import or_

    result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            or_(*conditions),
        )
        .limit(limit * 2)
    )
    nodes = result.scalars().all()

    # Score by number of matching terms (simple BM25-lite)
    scored = []
    for node in nodes:
        content_lower = (node.content or "").lower()
        title_lower = (node.title or "").lower()
        hit_count = sum(
            1 for t in terms
            if t.lower() in content_lower or t.lower() in title_lower
        )
        # Boost higher-level nodes (chapters > subsections)
        level_boost = max(0.5, 1.0 - node.level * 0.1)
        scored.append({
            "id": str(node.id),
            "title": node.title,
            "content": (node.content or "")[:1500],
            "level": node.level,
            "score": hit_count * level_boost,
            "source": "keyword",
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


async def vector_search(
    db: AsyncSession,
    course_id: uuid.UUID,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """pgvector cosine similarity search on content tree.

    Requires embeddings to be pre-computed. Falls back to empty
    if embeddings not available.
    """
    try:
        from services.memory.pipeline import _generate_embedding

        query_embedding = await _generate_embedding(query)
        if not query_embedding:
            return []

        # pgvector cosine distance search
        # Note: content_tree doesn't have embeddings yet in Phase 0
        # This searches conversation_memories as a fallback for now
        from models.memory import ConversationMemory

        result = await db.execute(
            select(ConversationMemory)
            .where(
                ConversationMemory.course_id == course_id,
                ConversationMemory.embedding.isnot(None),
            )
            .order_by(ConversationMemory.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        memories = result.scalars().all()
        return [
            {
                "id": str(m.id),
                "title": "Previous interaction",
                "content": m.summary or "",
                "level": 0,
                "score": 1.0,  # Scores will be normalized by RRF
                "source": "vector",
            }
            for m in memories
        ]
    except Exception as e:
        logger.debug(f"Vector search unavailable: {e}")
        return []


async def tree_search(
    db: AsyncSession,
    course_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """PageIndex-style tree reasoning search.

    Phase 1: Navigate the content tree hierarchically.
    Start from root nodes, check if query relates to each chapter,
    then drill down into matching subtrees.
    """
    # Get top-level nodes (chapters)
    result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.level <= 1,
        )
        .order_by(CourseContentTree.order_index)
    )
    chapters = result.scalars().all()

    if not chapters:
        return []

    # Simple relevance check: does the query relate to this chapter?
    query_lower = query.lower()
    relevant_chapters = []
    for ch in chapters:
        title_lower = (ch.title or "").lower()
        content_lower = (ch.content or "")[:500].lower()
        if any(term in title_lower or term in content_lower
               for term in query_lower.split() if len(term) >= 2):
            relevant_chapters.append(ch)

    if not relevant_chapters:
        relevant_chapters = chapters[:3]  # Fallback to first 3 chapters

    # Drill into relevant chapters for leaf content
    results = []
    for chapter in relevant_chapters[:3]:
        child_result = await db.execute(
            select(CourseContentTree)
            .where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.parent_id == chapter.id,
            )
            .order_by(CourseContentTree.order_index)
        )
        children = child_result.scalars().all()

        # Score children by query relevance
        for child in children:
            content_lower = (child.content or "").lower()
            hit_count = sum(
                1 for t in query_lower.split()
                if len(t) >= 2 and t in content_lower
            )
            if hit_count > 0 or len(children) <= 3:
                results.append({
                    "id": str(child.id),
                    "title": f"{chapter.title} > {child.title}",
                    "content": (child.content or "")[:1500],
                    "level": child.level,
                    "score": hit_count + 0.5,
                    "source": "tree",
                })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


async def hybrid_search(
    db: AsyncSession,
    course_id: uuid.UUID,
    query: str,
    limit: int = 5,
) -> list[dict]:
    """RRF fusion of keyword + tree + vector search results.

    Formula: final_score = sum(1/(60 + rank_i)) for each retriever.
    """
    # Run all three searches
    kw_results = await keyword_search(db, course_id, query, limit=limit * 2)
    tree_results = await tree_search(db, course_id, query, limit=limit)
    vec_results = await vector_search(db, course_id, query, limit=limit)

    # Assign RRF scores by rank in each result list
    score_map: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank, doc in enumerate(kw_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + rrf_score(rank)
        doc_map[doc_id] = doc

    for rank, doc in enumerate(tree_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + rrf_score(rank)
        doc_map[doc_id] = doc

    for rank, doc in enumerate(vec_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + rrf_score(rank)
        doc_map[doc_id] = doc

    # Sort by fused score
    ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)

    results = []
    for doc_id, score in ranked[:limit]:
        doc = doc_map[doc_id]
        doc["rrf_score"] = score
        results.append(doc)

    return results
