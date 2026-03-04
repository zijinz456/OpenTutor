"""Hybrid search with RRF fusion ranking.

Combines PageIndex tree search + vector similarity search using
Reciprocal Rank Fusion: score = 1/(k + rank), k=60 (standard).

Supports both PostgreSQL (pgvector + TSVECTOR) and SQLite (LIKE fallback).

Reference:
- spec Phase 1: RRF fusion ranking
- PageIndex: tree-based reasoning search (98.7% accuracy on FinanceBench)
- pgvector / sqlite-vec: cosine distance for semantic similarity
"""

import uuid
import logging
import re

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from database import is_sqlite
from models.content import CourseContentTree
from services.search.compat import cosine_similarity

logger = logging.getLogger(__name__)

# RRF constant (standard value from literature)
RRF_K = 60

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")
_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{1,}")


def rrf_score(rank: int) -> float:
    """Reciprocal Rank Fusion score: 1/(k + rank)."""
    return 1.0 / (RRF_K + rank)


def _contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _tokenize_query(query: str) -> list[str]:
    """Extract mixed English/CJK search terms without relying on whitespace."""
    terms: list[str] = []
    seen: set[str] = set()

    def _push(term: str) -> None:
        value = term.strip().lower()
        if len(value) < 2 or value in seen:
            return
        seen.add(value)
        terms.append(value)

    for match in _ASCII_TERM_RE.finditer(query):
        _push(match.group(0))

    for segment in _CJK_RE.findall(query):
        _push(segment)
        if len(segment) <= 2:
            continue
        for size in (2, 3):
            if len(segment) < size:
                continue
            for idx in range(len(segment) - size + 1):
                _push(segment[idx : idx + size])

    if not terms and query.strip():
        _push(query[:100])
    return terms[:12]


async def keyword_search(
    db: AsyncSession,
    course_id: uuid.UUID,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """BM25-style keyword search.

    PostgreSQL: Uses ts_rank_cd (cover density ranking) via TSVECTOR.
    SQLite: Falls back to LIKE-based term matching.
    """
    # Try full-text search first (PostgreSQL only)
    rows = []
    if not is_sqlite() and not _contains_cjk(query):
        result = await db.execute(
            text("""
                SELECT id, title, content, level,
                       ts_rank_cd(search_vector, plainto_tsquery('simple', :query), 32) AS rank
                FROM course_content_tree
                WHERE course_id = :course_id
                  AND search_vector IS NOT NULL
                  AND search_vector @@ plainto_tsquery('simple', :query)
                ORDER BY rank DESC
                LIMIT :limit
            """),
            {"course_id": str(course_id), "query": query, "limit": limit},
        )
        rows = result.fetchall()

    if rows:
        return [
            {
                "id": str(row.id),
                "title": row.title,
                "content": (row.content or "")[:1500],
                "level": row.level,
                "score": float(row.rank),
                "source": "bm25",
            }
            for row in rows
        ]

    # Fallback: LIKE-based search (SQLite default, PG fallback)
    terms = _tokenize_query(query)

    from sqlalchemy import or_
    conditions = [
        or_(
            CourseContentTree.title.ilike(f"%{t}%"),
            CourseContentTree.content.ilike(f"%{t}%"),
        )
        for t in terms[:6]
    ]

    result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id, or_(*conditions))
        .limit(limit * 2)
    )
    nodes = result.scalars().all()

    scored = []
    for node in nodes:
        content_lower = (node.content or "").lower()
        title_lower = (node.title or "").lower()
        hit_count = sum(
            1 for t in terms
            if t.lower() in content_lower or t.lower() in title_lower
        )
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
    """Cosine similarity search on content tree embeddings.

    PostgreSQL: Uses pgvector cosine_distance operator.
    SQLite: Falls back to brute-force Python cosine similarity
            (sufficient for small personal datasets).
    """
    try:
        from services.embedding.registry import get_embedding_provider
        provider = get_embedding_provider()
        query_embedding = await provider.embed(query)
    except Exception as e:
        logger.debug(f"Embedding unavailable: {e}")
        return []

    if is_sqlite():
        # SQLite: no native vector ops — load all embeddings and compute in Python.
        # This is fine for personal-scale datasets (< 10k nodes).
        result = await db.execute(
            select(CourseContentTree)
            .where(
                CourseContentTree.course_id == course_id,
                CourseContentTree.embedding.isnot(None),
            )
        )
        nodes = result.scalars().all()
        if not nodes:
            return []

        import json

        scored = []
        for n in nodes:
            emb = n.embedding
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except Exception:
                    continue
            if not emb:
                continue
            sim = cosine_similarity(query_embedding, emb)
            scored.append((n, sim))
        scored.sort(key=lambda x: x[1], reverse=True)

        return [
            {
                "id": str(n.id),
                "title": n.title,
                "content": (n.content or "")[:1500],
                "level": n.level,
                "score": sim,
                "source": "vector",
            }
            for n, sim in scored[:limit]
        ]

    # PostgreSQL: use pgvector cosine distance
    result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.embedding.isnot(None),
        )
        .order_by(CourseContentTree.embedding.cosine_distance(query_embedding))
        .limit(limit)
    )
    nodes = result.scalars().all()

    if nodes:
        return [
            {
                "id": str(n.id),
                "title": n.title,
                "content": (n.content or "")[:1500],
                "level": n.level,
                "score": 1.0,
                "source": "vector",
            }
            for n in nodes
        ]

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
    query_terms = _tokenize_query(query)
    relevant_chapters = []
    for ch in chapters:
        title_lower = (ch.title or "").lower()
        content_lower = (ch.content or "")[:500].lower()
        if any(term in title_lower or term in content_lower for term in query_terms):
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
                1 for t in query_terms
                if t in content_lower or t in (child.title or "").lower()
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
