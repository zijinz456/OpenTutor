"""RRF fusion: combines keyword, tree, and vector search results.

Reciprocal Rank Fusion: score = 1/(k + rank), k=60 (standard).

Reference:
- spec Phase 1: RRF fusion ranking
- PageIndex: tree-based reasoning search (98.7% accuracy on FinanceBench)
- cosine distance for semantic similarity
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.search.scoring import (
    _document_coverage_details,
    _document_signal_score,
    _tokenize_query,
    decompose_search_query,
    rrf_score,
)
from services.search.section_merge import _merge_section_hits
from services.search.strategies import keyword_search, tree_search, vector_search


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
