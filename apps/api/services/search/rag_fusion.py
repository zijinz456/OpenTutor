"""rag-fusion multi-query retrieval with RRF fusion.

Borrows from:
- rag-fusion project: user query → LLM generates N query variants → parallel retrieval → RRF fusion
- OpenClaw hybrid search: BM25 + vector fusion pattern

Key insight: A single query may miss relevant results due to vocabulary mismatch.
Generating multiple query perspectives and fusing results improves recall.
"""

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.llm.router import get_llm_client
from services.search.hybrid import decompose_search_query, hybrid_search

logger = logging.getLogger(__name__)

QUERY_GENERATION_PROMPT = """Generate {n} different search queries to find information relevant to the student's question.
Each query should approach the topic from a different angle or use different keywords.

Student's question: {query}
Course context: {course_context}

Output a JSON array of strings: ["query1", "query2", "query3"]
Keep each query under 50 words. Focus on different aspects of the question."""


async def generate_query_variants(
    query: str,
    n: int = 3,
    course_context: str = "",
) -> list[str]:
    """Generate N query variants using LLM (rag-fusion pattern)."""
    client = get_llm_client("fast")
    try:
        result, _ = await client.extract(
            "You are a search query generator. Output only a JSON array of strings.",
            QUERY_GENERATION_PROMPT.format(
                n=n, query=query[:200], course_context=course_context[:200],
            ),
        )
        result = result.strip()
        if "```" in result:
            json_start = result.find("[")
            json_end = result.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]

        variants = json.loads(result)
        if isinstance(variants, list):
            return [str(v) for v in variants[:n]]
    except (json.JSONDecodeError, ConnectionError, TimeoutError, ValueError, RuntimeError, Exception) as e:
        logger.warning("Query variant generation failed: %s", e, exc_info=True)

    return []


async def rag_fusion_search(
    db: AsyncSession,
    course_id: uuid.UUID,
    query: str,
    limit: int = 5,
    n_variants: int = 3,
    course_context: str = "",
) -> list[dict]:
    """Multi-query retrieval with RRF fusion (rag-fusion pattern).

    1. Generate N query variants from the original query
    2. Run hybrid_search for each variant (parallel)
    3. Fuse all results using RRF
    4. Return top-K unique results

    This improves recall for ambiguous or complex learning questions.
    """
    # Generate query variants
    variants = await generate_query_variants(query, n_variants, course_context)
    decomposed = decompose_search_query(query, max_facets=max(2, n_variants))

    # Always include the original query
    all_queries: list[str] = []
    seen: set[str] = set()
    for candidate in [query] + decomposed + variants:
        normalized = " ".join(candidate.strip().split()).lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        all_queries.append(candidate.strip())

    # Run hybrid search for each query
    all_results: list[list[dict]] = []
    for q in all_queries:
        results = await hybrid_search(db, course_id, q, limit=limit)
        all_results.append(results)

    # RRF fusion across all query results
    RRF_K = 60
    score_map: dict[str, float] = {}
    doc_map: dict[str, dict] = {}
    query_match_counts: dict[str, int] = {}

    for query_index, query_results in enumerate(all_results):
        query_text = all_queries[query_index]
        query_weight = 1.0 if query_index == 0 else (0.9 if query_text in decomposed else 0.75)
        for rank, doc in enumerate(query_results, start=1):
            doc_id = doc.get("id", "")
            if not doc_id:
                continue
            score_map[doc_id] = score_map.get(doc_id, 0) + query_weight * (1.0 / (RRF_K + rank))
            query_match_counts[doc_id] = query_match_counts.get(doc_id, 0) + 1
            existing = doc_map.get(doc_id)
            if existing is None or float(doc.get("hybrid_score", 0.0)) > float(existing.get("hybrid_score", 0.0)):
                doc_map[doc_id] = doc

    # Sort by fused score
    ranked = sorted(
        score_map.items(),
        key=lambda item: (
            item[1]
            + max(0, query_match_counts.get(item[0], 0) - 1) * 0.012
            + float(doc_map[item[0]].get("coverage_score", 0.0)),
            float(doc_map[item[0]].get("hybrid_score", 0.0)),
            item[1],
        ),
        reverse=True,
    )

    results = []
    for doc_id, score in ranked[:limit]:
        doc = dict(doc_map[doc_id])
        doc["fusion_score"] = score
        doc["query_count"] = query_match_counts.get(doc_id, 0)
        doc["query_variant_total"] = len(all_queries)
        results.append(doc)

    logger.debug(
        "rag-fusion: %d queries → %d unique results (top %d returned)",
        len(all_queries), len(score_map), len(results),
    )
    return results
