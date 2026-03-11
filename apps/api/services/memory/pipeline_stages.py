"""Memory pipeline stages: consolidate and retrieve.

Stage 2 (consolidate) — deduplication via word overlap + cosine similarity, importance decay.
Stage 3 (retrieve) — hybrid BM25 + vector search with RRF fusion.

Extracted from pipeline.py to keep each file focused on a single concern.
"""

import json
import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import ConversationMemory
from services.search.compat import cosine_similarity

from .pipeline import generate_embedding

logger = logging.getLogger(__name__)

_cosine_similarity = cosine_similarity

# ── Stage 2: CONSOLIDATE ──

# Single decay constant: 90 days half-life for all memory types
DECAY_HALF_LIFE_DAYS = 90


async def consolidate_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Stage 2: Consolidate memories — deduplicate and decay.

    Simplified:
    - Word overlap pre-filter (threshold 0.5) for candidate pairs
    - Embedding cosine similarity confirmation (threshold 0.85)
    - Single importance decay rate (90 days half-life for all types)
    """
    query = select(ConversationMemory).where(
        ConversationMemory.user_id == user_id,
        ConversationMemory.dismissed_at.is_(None),
    )
    if course_id:
        query = query.where(ConversationMemory.course_id == course_id)
    query = query.order_by(ConversationMemory.created_at.desc())

    result = await db.execute(query)
    memories = list(result.scalars().all())

    if len(memories) < 2:
        return {"deduped": 0, "decayed": 0}

    # Phase 1: Word overlap pre-filter (threshold 0.5)
    candidates: list[tuple] = []
    removed = set()
    for i, mem_a in enumerate(memories):
        if mem_a.id in removed:
            continue
        words_a = set(mem_a.summary.lower().split())
        if len(words_a) < 3:
            continue
        for j in range(i + 1, len(memories)):
            mem_b = memories[j]
            if mem_b.id in removed:
                continue
            # Only dedup within same type
            if mem_a.memory_type != mem_b.memory_type:
                continue
            words_b = set(mem_b.summary.lower().split())
            if len(words_b) < 3:
                continue
            overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
            if overlap >= 0.5:
                candidates.append((mem_a, mem_b, overlap))

    # Phase 2: Embedding cosine similarity confirmation (threshold 0.85)
    merged_pairs: list[tuple] = []
    for mem_a, mem_b, word_overlap in candidates:
        if mem_a.id in removed or mem_b.id in removed:
            continue
        is_duplicate = False
        if mem_a.embedding and mem_b.embedding:
            similarity = _cosine_similarity(mem_a.embedding, mem_b.embedding)
            if similarity >= 0.85:
                is_duplicate = True
        elif word_overlap >= 0.7:
            is_duplicate = True

        if is_duplicate:
            # Keep the more important one
            if mem_b.importance >= mem_a.importance:
                keeper, loser = mem_b, mem_a
            else:
                keeper, loser = mem_a, mem_b
            merged_pairs.append((keeper, loser))
            removed.add(loser.id)

    # Apply merges: boost keeper importance and accumulate access counts
    for keeper, loser in merged_pairs:
        keeper.importance = min(1.0, keeper.importance + loser.importance * 0.3)
        keeper.access_count = (keeper.access_count or 0) + (loser.access_count or 0)
        meta = keeper.metadata_json or {}
        meta["merge_count"] = meta.get("merge_count", 1) + 1
        meta["last_merged_at"] = datetime.now(timezone.utc).isoformat()
        keeper.metadata_json = meta

    for mem in memories:
        if mem.id in removed:
            await db.delete(mem)

    # Importance decay (single rate for all types)
    now = datetime.now(timezone.utc)
    decayed_count = 0
    for mem in memories:
        if mem.id in removed:
            continue
        days = (now - mem.created_at).total_seconds() / 86400
        decay = math.exp(-days / DECAY_HALF_LIFE_DAYS)
        new_importance = mem.importance * decay
        if new_importance < 0.1:
            await db.delete(mem)
            decayed_count += 1
        elif abs(new_importance - mem.importance) > 0.01:
            mem.importance = new_importance

    await db.flush()
    return {"deduped": len(removed), "decayed": decayed_count}


# ── Stage 3: RETRIEVE (Hybrid BM25 + Vector Search) ──

# Hybrid search weights
VECTOR_WEIGHT = 0.7
BM25_WEIGHT = 0.3
# RRF scores are tiny (max ~0.016 for rank-1 in both searches with K=60).
# Use an RRF-appropriate threshold (~25% of theoretical max).
RRF_MIN_SCORE = 0.004


async def retrieve_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None = None,
    limit: int = 5,
    memory_types: list[str] | None = None,
) -> list[dict]:
    """Stage 3: Hybrid BM25 + Vector retrieval with RRF fusion.

    - Keyword retrieval via lightweight BM25-style fallback (weight 0.3)
    - Vector cosine similarity in Python (weight 0.7)
    - RRF fusion ranking
    - minScore filtering (RRF_MIN_SCORE = 0.004, ~25% of theoretical max)
    """
    bm25_results = await _bm25_memory_search(db, user_id, query, course_id, limit * 2, memory_types)
    vector_results = await _vector_memory_search(db, user_id, query, course_id, limit * 2, memory_types)

    # RRF fusion
    RRF_K = 60
    score_map: dict[str, float] = {}
    doc_map: dict[str, dict] = {}

    for rank, doc in enumerate(bm25_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + BM25_WEIGHT / (RRF_K + rank)
        doc_map[doc_id] = doc

    for rank, doc in enumerate(vector_results, start=1):
        doc_id = doc["id"]
        score_map[doc_id] = score_map.get(doc_id, 0) + VECTOR_WEIGHT / (RRF_K + rank)
        doc_map[doc_id] = doc

    ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)

    results = []
    for doc_id, score in ranked[:limit]:
        if score < RRF_MIN_SCORE:
            continue
        doc = doc_map[doc_id]
        doc["hybrid_score"] = score
        results.append(doc)

    # Update access counts for retrieved memories
    for doc in results:
        await db.execute(
            text("UPDATE conversation_memories SET access_count = access_count + 1 WHERE id = :id"),
            {"id": doc["id"]},
        )
    if results:
        await db.flush()

    return results


async def _vector_memory_search(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None,
    limit: int,
    memory_types: list[str] | None,
) -> list[dict]:
    """Vector similarity search on memory embeddings."""
    query_embedding = await generate_embedding(query)
    if not query_embedding:
        return []

    base_query = (
        select(ConversationMemory)
        .where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.embedding.isnot(None),
            ConversationMemory.dismissed_at.is_(None),
        )
    )
    if course_id:
        base_query = base_query.where(ConversationMemory.course_id == course_id)
    if memory_types:
        base_query = base_query.where(ConversationMemory.memory_type.in_(memory_types))

    result = await db.execute(base_query)
    memories = result.scalars().all()

    scored = []
    for mem in memories:
        emb = mem.embedding
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except (json.JSONDecodeError, TypeError):
                continue
        if not emb:
            continue
        sim = _cosine_similarity(query_embedding, emb)
        if sim > 0.3:
            scored.append({
                "id": str(mem.id),
                "summary": mem.summary,
                "memory_type": mem.memory_type,
                "importance": mem.importance,
                "similarity": sim,
                "category": mem.category,
                "created_at": mem.created_at.isoformat(),
                "source": "vector",
            })
    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


async def _bm25_memory_search(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None,
    limit: int,
    memory_types: list[str] | None,
) -> list[dict]:
    """BM25 keyword search on memory content."""
    # SQLite mode: simple keyword matching fallback
    search_words = query.lower().split()[:5]
    base_query = (
        select(ConversationMemory)
        .where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.dismissed_at.is_(None),
        )
    )
    if course_id:
        base_query = base_query.where(ConversationMemory.course_id == course_id)
    if memory_types:
        base_query = base_query.where(ConversationMemory.memory_type.in_(memory_types))

    result = await db.execute(
        base_query.order_by(ConversationMemory.importance.desc()).limit(limit * 2)
    )
    memories = result.scalars().all()

    scored = []
    for mem in memories:
        words = mem.summary.lower().split()
        score = sum(1 for w in search_words if w in words) / max(len(search_words), 1)
        if score > 0:
            scored.append({
                "id": str(mem.id),
                "summary": mem.summary,
                "memory_type": mem.memory_type,
                "importance": mem.importance,
                "bm25_rank": score,
                "category": mem.category,
                "created_at": mem.created_at.isoformat(),
                "source": "keyword_fallback",
            })

    scored.sort(key=lambda x: x["bm25_rank"], reverse=True)
    return scored[:limit]
