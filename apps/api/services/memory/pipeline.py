"""Memory pipeline: encode → consolidate → retrieve.

Simplified from EverMemOS-style pipeline:
- Rule-based classification into 3 types (profile / knowledge / plan)
- Word overlap + cosine similarity dedup
- Single importance decay rate (90 days for all types)
- BM25 + Vector hybrid retrieval (unchanged)
"""

import json
import logging
import math
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import ConversationMemory
from services.search.compat import cosine_similarity, update_search_vector

logger = logging.getLogger(__name__)

# ── Rule-based memory type classification ──

_PROFILE_PATTERNS = re.compile(
    r"(i\s+(like|prefer|want|don'?t\s+like|hate|need|am\s+a|feel)|"
    r"my\s+(style|level|weakness|strength|preference)|"
    r"too\s+(fast|slow|detailed|brief|hard|easy)|"
    r"(visual|auditory|hands.?on)\s+learner)",
    re.IGNORECASE,
)

_PLAN_PATTERNS = re.compile(
    r"(deadline|exam|schedule|assignment|due\s+date|"
    r"study\s+plan|goal|target|timeline|midterm|final|"
    r"week\s+\d|tomorrow|next\s+week|before\s+the)",
    re.IGNORECASE,
)


def classify_memory_type(user_message: str, assistant_response: str = "") -> str:
    """Rule-based memory type classification (replaces LLM classification)."""
    text_combined = f"{user_message} {assistant_response}"
    if _PROFILE_PATTERNS.search(text_combined):
        return "profile"
    if _PLAN_PATTERNS.search(text_combined):
        return "plan"
    return "knowledge"


# ── Stage 1: ENCODE ──


async def encode_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    user_message: str,
    assistant_response: str,
) -> list[ConversationMemory]:
    """Stage 1: Create a memory entry from a conversation turn.

    Uses rule-based classification instead of LLM extraction.
    Returns list of created memory entries (0 or 1).
    """
    # Skip very short or trivial messages
    if len(user_message.strip()) < 10:
        return []

    # Build a concise summary from the conversation
    summary = _build_summary(user_message, assistant_response)
    if not summary or len(summary) < 10:
        return []

    mem_type = classify_memory_type(user_message, assistant_response)
    embedding = await generate_embedding(summary)

    memory = ConversationMemory(
        user_id=user_id,
        course_id=course_id,
        summary=summary,
        memory_type=mem_type,
        embedding=embedding,
        importance=0.5,
        source_message=user_message[:200],
        metadata_json={"source": "rule_based"},
    )
    db.add(memory)
    await db.flush()

    # Update search vector for BM25
    await update_search_vector(db, "conversation_memories", str(memory.id), summary)
    await db.flush()
    logger.info("Memory encoded (type=%s) for user %s", mem_type, user_id)
    return [memory]


# Also export as encode_memories for callers that use the plural form
encode_memories = encode_memory


def _build_summary(user_message: str, assistant_response: str) -> str:
    """Build a concise memory summary from conversation turn.

    Extracts the key information without LLM — just truncates and combines.
    """
    user_part = user_message.strip()[:300]
    assistant_part = assistant_response.strip()[:300]

    # For very short assistant responses, just use the user message
    if len(assistant_part) < 20:
        return user_part

    return f"Student asked: {user_part}\nTutor responded: {assistant_part}"


async def generate_embedding(text_content: str) -> list[float] | None:
    """Generate embedding vector for text using the embedding service registry."""
    try:
        from services.embedding.registry import get_embedding_provider
        provider = get_embedding_provider()
        return await provider.embed(text_content)
    except Exception as e:
        logger.exception("Embedding generation failed")
        return None


# ── Stage 2: CONSOLIDATE ──

_cosine_similarity = cosine_similarity

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
MIN_SCORE = 0.35


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
    - minScore filtering (0.35 threshold)
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
        if score < MIN_SCORE / 1000:
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
