"""Hybrid search with RRF fusion ranking.

Combines PageIndex tree search + vector similarity search using
Reciprocal Rank Fusion: score = 1/(k + rank), k=60 (standard).

Reference:
- spec Phase 1: RRF fusion ranking
- PageIndex: tree-based reasoning search (98.7% accuracy on FinanceBench)
- cosine distance for semantic similarity
"""

import uuid
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def decompose_search_query(query: str, max_facets: int = 4) -> list[str]:
    """Split complex study questions into focused retrieval facets."""
    normalized = " ".join((query or "").strip().split())
    if not normalized:
        return []

    facets: list[str] = []
    seen: set[str] = set()

    def _push(candidate: str) -> None:
        value = " ".join(candidate.strip().split())
        if len(value) < 4:
            return
        lowered = value.lower()
        if lowered == normalized.lower() or lowered in seen:
            return
        seen.add(lowered)
        facets.append(value)

    for quoted in re.findall(r'"([^"]+)"', normalized):
        _push(quoted)

    parts = re.split(r"\b(?:and|or|vs|versus)\b|[;,/]", normalized, flags=re.IGNORECASE)
    for part in parts:
        _push(part)

    salient = _tokenize_query(normalized)
    if len(salient) >= 4:
        _push(" ".join(salient[:2]))
        _push(" ".join(salient[2:4]))

    return facets[:max_facets]


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


def _normalize_source_score(source: str, raw_score: float) -> float:
    if raw_score <= 0:
        return 0.0
    if source == "vector":
        return max(0.0, min(raw_score, 1.0))
    if source in {"bm25", "keyword", "tree"}:
        return min(raw_score / 5.0, 1.0)
    return min(raw_score / 5.0, 1.0)


def _facet_match_ratio(text: str, facet: str) -> float:
    normalized_text = _normalize_text(text)
    normalized_facet = _normalize_text(facet)
    if not normalized_text or not normalized_facet:
        return 0.0
    if normalized_facet in normalized_text:
        return 1.0
    facet_terms = _tokenize_query(normalized_facet)
    if not facet_terms:
        return 0.0
    matched = sum(1 for term in facet_terms if term in normalized_text)
    return matched / len(facet_terms)


def _document_coverage_details(doc: dict, query: str, facets: list[str]) -> dict[str, object]:
    title = str(doc.get("title") or "")
    content = str(doc.get("content") or "")
    combined = f"{title}\n{content}"
    evidence_terms = _tokenize_query(query)
    matched_terms = [term for term in evidence_terms if term in _normalize_text(combined)]
    matched_facets = [facet for facet in facets if _facet_match_ratio(combined, facet) >= 0.6]
    evidence_coverage = len(set(matched_terms)) / max(len(set(evidence_terms)), 1) if evidence_terms else 0.0
    facet_coverage = len(matched_facets) / max(len(facets), 1) if facets else 0.0
    coverage_score = round((evidence_coverage * 0.03) + (facet_coverage * 0.028), 6)
    return {
        "matched_terms": matched_terms[:10],
        "matched_facets": matched_facets[:6],
        "evidence_coverage": round(evidence_coverage, 3),
        "facet_coverage": round(facet_coverage, 3),
        "coverage_score": coverage_score,
    }


def _section_group_key(doc: dict) -> str:
    source_file = str(doc.get("source_file") or "")
    parent_id = str(doc.get("parent_id") or "")
    title = _normalize_text(str(doc.get("title") or ""))
    if parent_id:
        return f"{source_file}|{parent_id}"
    return f"{source_file}|{title[:120]}"


def _merge_section_hits(results: list[dict], limit: int) -> list[dict]:
    """Collapse near-duplicate hits from the same section into one richer result."""
    merged: list[dict] = []
    merged_by_key: dict[str, dict] = {}

    for doc in results:
        key = _section_group_key(doc)
        existing = merged_by_key.get(key)
        if existing is None:
            primary = dict(doc)
            primary["section_key"] = key
            primary["section_hit_count"] = 1
            primary["supporting_hit_ids"] = []
            primary["supporting_snippets"] = []
            merged_by_key[key] = primary
            merged.append(primary)
            continue

        existing["section_hit_count"] = int(existing.get("section_hit_count") or 1) + 1
        supporting_ids = list(existing.get("supporting_hit_ids") or [])
        if doc.get("id") and doc.get("id") not in supporting_ids and doc.get("id") != existing.get("id"):
            supporting_ids.append(str(doc["id"]))
        existing["supporting_hit_ids"] = supporting_ids[:5]

        snippets = list(existing.get("supporting_snippets") or [])
        snippet = str(doc.get("content") or "")[:180].strip()
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        existing["supporting_snippets"] = snippets[:3]

        existing["source_hits"] = sorted({
            *(existing.get("source_hits") or []),
            *(doc.get("source_hits") or []),
        })
        existing["matched_terms"] = sorted({
            *(existing.get("matched_terms") or []),
            *(doc.get("matched_terms") or []),
        })[:12]
        existing["matched_facets"] = sorted({
            *(existing.get("matched_facets") or []),
            *(doc.get("matched_facets") or []),
        })[:8]
        existing["evidence_coverage"] = round(
            max(float(existing.get("evidence_coverage") or 0.0), float(doc.get("evidence_coverage") or 0.0)),
            3,
        )
        existing["facet_coverage"] = round(
            max(float(existing.get("facet_coverage") or 0.0), float(doc.get("facet_coverage") or 0.0)),
            3,
        )
        existing["coverage_score"] = round(
            max(float(existing.get("coverage_score") or 0.0), float(doc.get("coverage_score") or 0.0))
            + (int(existing.get("section_hit_count") or 1) - 1) * 0.006,
            6,
        )
        existing["hybrid_score"] = round(
            max(float(existing.get("hybrid_score") or 0.0), float(doc.get("hybrid_score") or 0.0))
            + (int(existing.get("section_hit_count") or 1) - 1) * 0.008,
            6,
        )

        if float(doc.get("hybrid_score") or 0.0) > float(existing.get("hybrid_score") or 0.0):
            previous_primary_id = existing.get("id")
            if previous_primary_id and previous_primary_id != doc.get("id") and previous_primary_id not in existing["supporting_hit_ids"]:
                existing["supporting_hit_ids"] = [*existing["supporting_hit_ids"], str(previous_primary_id)][:5]
            existing["id"] = doc.get("id")
            existing["title"] = doc.get("title")
            existing["content"] = doc.get("content")
            existing["level"] = doc.get("level")
            existing["score"] = doc.get("score")
            existing["source"] = doc.get("source")
            existing["rrf_score"] = doc.get("rrf_score")
            existing["signal_score"] = doc.get("signal_score")

    merged.sort(
        key=lambda item: (
            float(item.get("hybrid_score") or 0.0),
            int(item.get("section_hit_count") or 1),
            float(item.get("rrf_score") or 0.0),
        ),
        reverse=True,
    )
    top = merged[:limit]
    for item in top:
        summary_bits: list[str] = []
        matched_facets = list(item.get("matched_facets") or [])
        matched_terms = list(item.get("matched_terms") or [])
        supporting_snippets = list(item.get("supporting_snippets") or [])
        if matched_facets:
            summary_bits.append(f"Matches: {', '.join(matched_facets[:2])}")
        elif matched_terms:
            summary_bits.append(f"Key terms: {', '.join(matched_terms[:4])}")
        if supporting_snippets:
            summary_bits.append(supporting_snippets[0][:140])
        else:
            preview = str(item.get("content") or "").strip()
            if preview:
                summary_bits.append(preview[:140])
        item["evidence_summary"] = " — ".join(bit for bit in summary_bits if bit)[:320]
    return top


def _document_signal_score(doc: dict, query: str, terms: list[str]) -> float:
    """Compute lightweight lexical/structural relevance for post-fusion reranking."""
    if not terms:
        return 0.0

    title = _normalize_text(str(doc.get("title") or ""))
    content = _normalize_text(str(doc.get("content") or ""))
    normalized_query = _normalize_text(query)

    title_hits = sum(1 for term in terms if term in title)
    content_hits = sum(1 for term in terms if term in content)
    unique_hits = sum(1 for term in terms if term in title or term in content)
    term_count = max(len(terms), 1)
    coverage = unique_hits / term_count
    title_ratio = title_hits / term_count
    content_ratio = content_hits / term_count

    phrase_in_title = bool(normalized_query and normalized_query in title)
    phrase_in_content = bool(normalized_query and normalized_query in content)

    level = int(doc.get("level") or 0)
    level_boost = max(0.0, 1.0 - (level * 0.12))
    source_score = _normalize_source_score(str(doc.get("source") or ""), float(doc.get("score") or 0.0))

    signal = 0.0
    signal += coverage * 0.03
    signal += title_ratio * 0.025
    signal += content_ratio * 0.018
    signal += source_score * 0.015
    signal += level_boost * 0.01
    if phrase_in_title:
        signal += 0.03
    if phrase_in_content:
        signal += 0.02
    return round(signal, 6)


async def keyword_search(
    db: AsyncSession,
    course_id: uuid.UUID,
    query: str,
    limit: int = 10,
) -> list[dict]:
    """Keyword search using LIKE-based term matching."""
    terms = _tokenize_query(query)
    for facet in decompose_search_query(query):
        for token in _tokenize_query(facet):
            if token not in terms:
                terms.append(token)
    if not terms:
        return []

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
            "parent_id": str(node.parent_id) if node.parent_id else None,
            "source_file": node.source_file,
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
    """Cosine similarity search on content tree embeddings."""
    try:
        from services.embedding.registry import get_embedding_provider
        provider = get_embedding_provider()
        query_embedding = await provider.embed(query)
    except Exception as e:
        logger.debug(f"Embedding unavailable: {e}")
        return []

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
            "parent_id": str(n.parent_id) if n.parent_id else None,
            "source_file": n.source_file,
            "score": sim,
            "source": "vector",
        }
        for n, sim in scored[:limit]
    ]


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
                    "parent_id": str(child.parent_id) if child.parent_id else None,
                    "source_file": child.source_file,
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
    terms = _tokenize_query(query)
    facets = decompose_search_query(query)

    # Assign RRF scores by rank in each result list
    score_map: dict[str, float] = {}
    doc_map: dict[str, dict] = {}
    source_hits: dict[str, set[str]] = {}

    for rank, doc in enumerate(kw_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + rrf_score(rank)
        doc_map[doc_id] = doc
        source_hits.setdefault(doc_id, set()).add("keyword")

    for rank, doc in enumerate(tree_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + rrf_score(rank)
        doc_map[doc_id] = doc
        source_hits.setdefault(doc_id, set()).add("tree")

    for rank, doc in enumerate(vec_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + rrf_score(rank)
        doc_map[doc_id] = doc
        source_hits.setdefault(doc_id, set()).add("vector")

    # Sort by fused score
    scored_docs: list[dict] = []
    for doc_id, score in score_map.items():
        doc = dict(doc_map[doc_id])
        coverage = _document_coverage_details(doc, query, facets)
        doc["rrf_score"] = score
        doc["signal_score"] = _document_signal_score(doc, query, terms)
        doc["coverage_score"] = coverage["coverage_score"]
        doc["evidence_coverage"] = coverage["evidence_coverage"]
        doc["facet_coverage"] = coverage["facet_coverage"]
        doc["matched_terms"] = coverage["matched_terms"]
        doc["matched_facets"] = coverage["matched_facets"]
        doc["query_facets"] = facets
        doc["source_hits"] = sorted(source_hits.get(doc_id, set()))
        doc["hybrid_score"] = round(
            doc["rrf_score"]
            + doc["signal_score"]
            + doc["coverage_score"]
            + (len(source_hits.get(doc_id, set())) - 1) * 0.01,
            6,
        )
        scored_docs.append(doc)

    scored_docs.sort(
        key=lambda item: (
            float(item.get("hybrid_score") or 0.0),
            float(item.get("rrf_score") or 0.0),
        ),
        reverse=True,
    )
    return _merge_section_hits(scored_docs, limit)
