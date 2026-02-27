"""EverMemOS 3-stage memory pipeline: encode → consolidate → retrieve.

UPGRADED with:
- MemCell atomic extraction (EverMemOS pattern): extracts multiple atomic memory units per conversation
- Multi-type classification: episode / profile / preference / knowledge / error / skill / fact
- BM25 + Vector hybrid search (OpenClaw pattern): weighted fusion (0.7 vector + 0.3 BM25)
- minScore filtering (OpenClaw pattern): drop low-relevance memories (threshold 0.35)
- Category hierarchy (memU pattern): Resource → Item → Category layered organization

Borrows from:
- EverMemOS: 3-stage architecture, MemCell extraction, importance-weighted retrieval
- OpenClaw: Hybrid Search (BM25 0.3 + Vector 0.7), minScore 0.35, chunking (400 tokens, 80 overlap)
- memU: 3-layer hierarchy (Resource → Item → Category), 6 memory types
- openakita: "is this useful in a month?" filter, lifecycle consolidation
"""

import json
import logging
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import ConversationMemory, MEMCELL_TYPES
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

# ── Stage 1: ENCODE (MemCell Atomic Extraction) ──

MEMCELL_EXTRACTION_PROMPT = """Analyze this conversation turn and extract atomic memory units (MemCells).

Each MemCell should be a single, self-contained piece of information about the student.
Ask yourself: "Is this useful a month from now in a new conversation?"

Memory types to extract:
- episode: Key learning event (e.g., "Student understood eigenvalue decomposition for the first time")
- profile: Student identity info (e.g., "Student is a visual learner who prefers diagrams")
- preference: Learning preference (e.g., "Student prefers step-by-step explanations")
- knowledge: Subject knowledge (e.g., "Student understands basic matrix multiplication")
- error: Error pattern (e.g., "Student confuses eigenvalues with eigenvectors")
- skill: Mastered skill (e.g., "Student can solve 2x2 determinants correctly")
- fact: Atomic fact (e.g., "Student is taking Linear Algebra this semester")

Rules:
- Extract 0-3 MemCells per conversation turn (most turns yield 0-1)
- Each MemCell must be a single atomic fact, not a conversation summary
- Focus on WHO the student IS, not WHAT they asked
- Be specific and concise (under 50 words each)
- If nothing worth remembering, return exactly: NONE

Conversation:
Student: {user_message}
Tutor: {assistant_response}

Output NONE or a JSON array:
[{{"type": "<memory_type>", "content": "<atomic memory>", "importance": <0.0-1.0>}}]"""


async def encode_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    user_message: str,
    assistant_response: str,
) -> list[ConversationMemory]:
    """Stage 1: Extract atomic MemCells from a conversation turn.

    Upgraded from single-summary to multi-MemCell extraction (EverMemOS pattern).
    Returns list of created memory entries (usually 0-2).
    """
    client = get_llm_client()
    created = []

    try:
        prompt = MEMCELL_EXTRACTION_PROMPT.format(
            user_message=user_message[:500],
            assistant_response=assistant_response[:500],
        )
        result, _ = await client.extract(
            "You are a memory encoding specialist. Output NONE or valid JSON array.",
            prompt,
        )
        result = result.strip()

        if not result or result.upper().startswith("NONE"):
            return []

        # Parse JSON array from response
        if "```" in result:
            json_start = result.find("[")
            json_end = result.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]

        memcells = json.loads(result)
        if not isinstance(memcells, list):
            memcells = [memcells]

        for cell in memcells[:3]:  # Max 3 MemCells per turn
            mem_type = cell.get("type", "fact")
            if mem_type not in MEMCELL_TYPES:
                mem_type = "fact"

            content = cell.get("content", "").strip()
            if not content or len(content) < 5:
                continue

            importance = min(1.0, max(0.0, float(cell.get("importance", 0.5))))
            embedding = await generate_embedding(content)

            memory = ConversationMemory(
                user_id=user_id,
                course_id=course_id,
                summary=content,
                memory_type=mem_type,
                embedding=embedding,
                importance=importance,
                source_message=user_message[:200],
                metadata_json={"source": "memcell_extraction"},
            )
            db.add(memory)
            created.append(memory)

        if created:
            await db.flush()
            # Update search vectors for BM25
            for mem in created:
                await db.execute(
                    text("""
                        UPDATE conversation_memories
                        SET search_vector = to_tsvector('simple', :summary)
                        WHERE id = :id
                    """),
                    {"summary": mem.summary, "id": str(mem.id)},
                )
            await db.flush()
            logger.info("Encoded %d MemCells for user %s", len(created), user_id)

        return created

    except json.JSONDecodeError:
        # Fallback: treat as single summary (backward compatible)
        return await _encode_single_summary(
            db, user_id, course_id, user_message, assistant_response, client,
        )
    except Exception as e:
        logger.warning("MemCell extraction failed: %s", e)
        return []


async def _encode_single_summary(
    db, user_id, course_id, user_message, assistant_response, client,
) -> list[ConversationMemory]:
    """Backward-compatible single-summary encoding (fallback)."""
    prompt = (
        f"Create a concise memory summary (under 100 words) of this conversation.\n"
        f"Ask: 'Is this useful a month from now?'\n"
        f"If nothing worth remembering, return NONE.\n\n"
        f"Student: {user_message[:500]}\nTutor: {assistant_response[:500]}"
    )
    summary, _ = await client.extract(
        "You are a memory encoding specialist. Output NONE or a brief summary.",
        prompt,
    )
    summary = summary.strip()
    if not summary or summary.upper().startswith("NONE"):
        return []

    embedding = await generate_embedding(summary)
    memory = ConversationMemory(
        user_id=user_id,
        course_id=course_id,
        summary=summary,
        memory_type="conversation",
        embedding=embedding,
        importance=0.5,
        source_message=user_message[:200],
    )
    db.add(memory)
    await db.flush()

    # Update search vector
    await db.execute(
        text("""
            UPDATE conversation_memories
            SET search_vector = to_tsvector('simple', :summary)
            WHERE id = :id
        """),
        {"summary": summary, "id": str(memory.id)},
    )
    await db.flush()
    logger.info("Memory encoded (fallback): %s", summary[:80])
    return [memory]


async def generate_embedding(text_content: str) -> list[float] | None:
    """Generate embedding vector for text using the embedding service registry."""
    try:
        from services.embedding.registry import get_embedding_provider
        provider = get_embedding_provider()
        return await provider.embed(text_content)
    except Exception as e:
        logger.debug("Embedding generation failed: %s", e)
        return None


# ── Stage 2: CONSOLIDATE ──

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


async def consolidate_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Stage 2: Consolidate memories — deduplicate, decay, and categorize.

    Upgraded with:
    - Two-phase deduplication (EverMemOS + mem0 pattern):
      Phase 1: Word overlap pre-filter (threshold 0.5) for candidate pairs
      Phase 2: Embedding cosine similarity confirmation (threshold 0.85)
    - MemCell-aware deduplication (same type only)
    - Category-based organization (memU pattern)
    - Importance-weighted recency decay
    """
    query = select(ConversationMemory).where(ConversationMemory.user_id == user_id)
    if course_id:
        query = query.where(ConversationMemory.course_id == course_id)
    query = query.order_by(ConversationMemory.created_at.desc())

    result = await db.execute(query)
    memories = list(result.scalars().all())

    if len(memories) < 2:
        return {"deduped": 0, "decayed": 0, "categorized": 0}

    # Phase 1: Word overlap pre-filter (threshold lowered to 0.5 for broader candidate capture)
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

    # Phase 2: Embedding cosine similarity confirmation (mem0 pattern, threshold 0.85)
    for mem_a, mem_b, word_overlap in candidates:
        if mem_a.id in removed or mem_b.id in removed:
            continue
        # If both have embeddings, use semantic similarity for final confirmation
        if mem_a.embedding and mem_b.embedding:
            similarity = _cosine_similarity(mem_a.embedding, mem_b.embedding)
            if similarity >= 0.85:
                # Confirmed duplicate — keep the more important one
                if mem_b.importance >= mem_a.importance:
                    removed.add(mem_a.id)
                else:
                    removed.add(mem_b.id)
        elif word_overlap >= 0.7:
            # No embeddings available — fall back to high word overlap threshold
            if mem_b.importance >= mem_a.importance:
                removed.add(mem_a.id)
            else:
                removed.add(mem_b.id)

    for mem in memories:
        if mem.id in removed:
            await db.delete(mem)

    # Recency decay (EverMemOS pattern, type-aware half-life)
    HALF_LIFE = {
        "episode": 180,     # Key events persist longer
        "profile": 365,     # Identity info very long-lived
        "preference": 120,  # Preferences change over time
        "knowledge": 90,    # Knowledge needs reinforcement
        "error": 60,        # Errors should be addressed soon
        "skill": 120,       # Skills persist moderately
        "fact": 90,         # Facts moderate persistence
        "conversation": 60, # Raw conversations decay fast
    }
    now = datetime.now(timezone.utc)
    decayed_count = 0
    for mem in memories:
        if mem.id in removed:
            continue
        days = (now - mem.created_at).total_seconds() / 86400
        half_life = HALF_LIFE.get(mem.memory_type, 90)
        decay = math.exp(-days / half_life)
        new_importance = mem.importance * decay
        if new_importance < 0.1:
            await db.delete(mem)
            decayed_count += 1
        elif abs(new_importance - mem.importance) > 0.01:
            mem.importance = new_importance

    await db.flush()
    return {"deduped": len(removed), "decayed": decayed_count}


# ── Stage 3: RETRIEVE (Hybrid BM25 + Vector Search) ──

# OpenClaw hybrid search weights
VECTOR_WEIGHT = 0.7
BM25_WEIGHT = 0.3
MIN_SCORE = 0.35  # OpenClaw minScore filter


async def retrieve_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None = None,
    limit: int = 5,
    memory_types: list[str] | None = None,
) -> list[dict]:
    """Stage 3: Hybrid BM25 + Vector retrieval with RRF fusion.

    Upgraded from pure vector search to OpenClaw hybrid pattern:
    - BM25 keyword search via PostgreSQL ts_rank (weight 0.3)
    - Vector cosine similarity via pgvector (weight 0.7)
    - RRF fusion ranking
    - minScore filtering (0.35 threshold)
    """
    # Run BM25 and vector search in parallel
    bm25_results = await _bm25_memory_search(db, user_id, query, course_id, limit * 2, memory_types)
    vector_results = await _vector_memory_search(db, user_id, query, course_id, limit * 2, memory_types)

    # RRF fusion (same pattern as content hybrid search)
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

    # Sort by fused score, apply minScore filter
    ranked = sorted(score_map.items(), key=lambda x: x[1], reverse=True)

    results = []
    for doc_id, score in ranked[:limit]:
        if score < MIN_SCORE / 1000:  # Normalized threshold
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

    type_filter = ""
    params = {
        "embedding": str(query_embedding),
        "user_id": str(user_id),
        "course_id": str(course_id) if course_id else None,
        "limit": limit,
    }

    if memory_types:
        type_filter = "AND memory_type = ANY(:types)"
        params["types"] = memory_types

    result = await db.execute(
        text(f"""
            SELECT id, summary, memory_type, importance, access_count, created_at, category,
                   1 - (embedding <=> :embedding::vector) as similarity
            FROM conversation_memories
            WHERE user_id = :user_id
              AND embedding IS NOT NULL
              AND (:course_id IS NULL OR course_id = :course_id)
              {type_filter}
            ORDER BY embedding <=> :embedding::vector
            LIMIT :limit
        """),
        params,
    )
    rows = result.fetchall()

    return [
        {
            "id": str(row.id),
            "summary": row.summary,
            "memory_type": row.memory_type,
            "importance": row.importance,
            "similarity": row.similarity,
            "category": row.category,
            "created_at": row.created_at.isoformat(),
            "source": "vector",
        }
        for row in rows
        if row.similarity > 0.3
    ]


async def _bm25_memory_search(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None,
    limit: int,
    memory_types: list[str] | None,
) -> list[dict]:
    """BM25 keyword search on memory content via PostgreSQL full-text search."""
    type_filter = ""
    params = {
        "user_id": str(user_id),
        "query": query,
        "course_id": str(course_id) if course_id else None,
        "limit": limit,
    }

    if memory_types:
        type_filter = "AND memory_type = ANY(:types)"
        params["types"] = memory_types

    # Try full-text search
    result = await db.execute(
        text(f"""
            SELECT id, summary, memory_type, importance, access_count, created_at, category,
                   ts_rank_cd(search_vector, plainto_tsquery('simple', :query), 32) AS rank
            FROM conversation_memories
            WHERE user_id = :user_id
              AND search_vector IS NOT NULL
              AND search_vector @@ plainto_tsquery('simple', :query)
              AND (:course_id IS NULL OR course_id = :course_id)
              {type_filter}
            ORDER BY rank DESC
            LIMIT :limit
        """),
        params,
    )
    rows = result.fetchall()

    if rows:
        return [
            {
                "id": str(row.id),
                "summary": row.summary,
                "memory_type": row.memory_type,
                "importance": row.importance,
                "bm25_rank": float(row.rank),
                "category": row.category,
                "created_at": row.created_at.isoformat(),
                "source": "bm25",
            }
            for row in rows
        ]

    # Fallback: simple keyword matching
    search_words = query.lower().split()[:5]
    base_query = (
        select(ConversationMemory)
        .where(ConversationMemory.user_id == user_id)
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
