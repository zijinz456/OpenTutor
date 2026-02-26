"""EverMemOS 3-stage memory pipeline: encode → consolidate → retrieve.

Borrows from:
- EverMemOS: 3-stage architecture, MaxSim scoring, importance-weighted retrieval
- openakita lifecycle: consolidation with deduplication + decay
- openakita extractor: entity-attribute extraction with "is this useful in a month?" filter

Phase 0-C: Simplified version — encode conversations, retrieve by vector similarity.
Phase 1: Full pipeline with BM25 + semantic hybrid, atomic facts, consolidation.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import ConversationMemory
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

# ── Stage 1: ENCODE ──

ENCODE_PROMPT = """Analyze this conversation turn and create a concise memory summary.

Rules (borrowed from openakita):
- Ask yourself: "Is this useful a month from now in a new conversation?"
- Record WHO the user IS (identity, preferences, learning style), not WHAT they want to DO
- Keep it under 100 words
- Focus on: learning preferences, knowledge gaps, mastery areas, study patterns

If there's nothing worth remembering, return exactly: NONE

Conversation:
Student: {user_message}
Tutor: {assistant_response}

Output either NONE or a concise memory summary:"""


async def encode_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    user_message: str,
    assistant_response: str,
) -> ConversationMemory | None:
    """Stage 1: Encode a conversation turn into a memory entry.

    Uses LLM to extract summary, then generates embedding for vector search.
    ~95% of conversations should return NONE (openakita "默认不提取" pattern).
    """
    client = get_llm_client()

    try:
        prompt = ENCODE_PROMPT.format(
            user_message=user_message[:500],
            assistant_response=assistant_response[:500],
        )
        summary = await client.extract(
            "You are a memory encoding specialist. Output NONE or a brief summary.",
            prompt,
        )
        summary = summary.strip()

        if not summary or summary.upper().startswith("NONE"):
            return None

        # Generate embedding via LLM provider (Phase 0-C: placeholder embedding)
        # Phase 1: Use OpenAI ada-002 or sentence-transformers
        embedding = await _generate_embedding(summary)

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

        logger.info(f"Memory encoded: {summary[:80]}")
        return memory

    except Exception as e:
        logger.warning(f"Memory encoding failed: {e}")
        return None


async def _generate_embedding(text: str) -> list[float] | None:
    """Generate embedding vector for text.

    Phase 0-C: Uses OpenAI embeddings API if available.
    Falls back to None (skips vector search).
    """
    try:
        from config import settings

        if settings.openai_api_key:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            response = await client.embeddings.create(
                model="text-embedding-3-small",
                input=text[:8000],
            )
            return response.data[0].embedding
    except Exception as e:
        logger.debug(f"Embedding generation failed: {e}")

    return None


# ── Stage 2: CONSOLIDATE ──

async def consolidate_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Stage 2: Consolidate memories — deduplicate and decay.

    Borrowed from openakita lifecycle.consolidate_daily:
    1. Find duplicate/overlapping memories (word overlap clustering)
    2. Keep highest-importance, remove duplicates
    3. Apply recency decay to older memories

    Phase 0-C: Simple word-overlap deduplication.
    Phase 1: LLM-driven review, experience synthesis.
    """
    import math

    query = select(ConversationMemory).where(ConversationMemory.user_id == user_id)
    if course_id:
        query = query.where(ConversationMemory.course_id == course_id)
    query = query.order_by(ConversationMemory.created_at.desc())

    result = await db.execute(query)
    memories = list(result.scalars().all())

    if len(memories) < 2:
        return {"deduped": 0, "decayed": 0}

    # Deduplication via word overlap (openakita O(n²) clustering)
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
            words_b = set(mem_b.summary.lower().split())
            if len(words_b) < 3:
                continue
            overlap = len(words_a & words_b) / min(len(words_a), len(words_b))
            if overlap >= 0.7:
                # Keep higher importance, remove the other
                if mem_b.importance >= mem_a.importance:
                    removed.add(mem_a.id)
                    break
                else:
                    removed.add(mem_b.id)

    # Delete duplicates
    for mem in memories:
        if mem.id in removed:
            await db.delete(mem)

    # Apply recency decay (EverMemOS pattern)
    now = datetime.now(timezone.utc)
    decayed_count = 0
    for mem in memories:
        if mem.id in removed:
            continue
        days = (now - mem.created_at).total_seconds() / 86400
        decay = math.exp(-days / 90)  # 90-day half-life
        new_importance = mem.importance * decay
        if new_importance < 0.1:
            await db.delete(mem)
            decayed_count += 1
        elif abs(new_importance - mem.importance) > 0.01:
            mem.importance = new_importance

    await db.flush()
    return {"deduped": len(removed), "decayed": decayed_count}


# ── Stage 3: RETRIEVE ──

async def retrieve_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    query: str,
    course_id: uuid.UUID | None = None,
    limit: int = 5,
) -> list[dict]:
    """Stage 3: Retrieve relevant memories using vector similarity.

    EverMemOS MaxSim pattern: find most semantically similar memories.
    Falls back to keyword search if embeddings aren't available.

    Phase 0-C: Simple vector cosine distance via pgvector.
    Phase 1: Hybrid BM25 + semantic + MaxSim with RRF fusion.
    """
    # Try vector search first
    query_embedding = await _generate_embedding(query)

    if query_embedding:
        # pgvector cosine distance search
        result = await db.execute(
            text("""
                SELECT id, summary, memory_type, importance, access_count, created_at,
                       1 - (embedding <=> :embedding::vector) as similarity
                FROM conversation_memories
                WHERE user_id = :user_id
                  AND embedding IS NOT NULL
                  AND (:course_id IS NULL OR course_id = :course_id)
                ORDER BY embedding <=> :embedding::vector
                LIMIT :limit
            """),
            {
                "embedding": str(query_embedding),
                "user_id": str(user_id),
                "course_id": str(course_id) if course_id else None,
                "limit": limit,
            },
        )
        rows = result.fetchall()

        # Update access counts
        for row in rows:
            await db.execute(
                text("UPDATE conversation_memories SET access_count = access_count + 1 WHERE id = :id"),
                {"id": str(row.id)},
            )
        await db.flush()

        return [
            {
                "summary": row.summary,
                "memory_type": row.memory_type,
                "importance": row.importance,
                "similarity": row.similarity,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
            if row.similarity > 0.3  # Minimum similarity threshold
        ]

    # Fallback: keyword search (like BM25 lite)
    search_words = query.lower().split()[:5]
    base_query = (
        select(ConversationMemory)
        .where(ConversationMemory.user_id == user_id)
    )
    if course_id:
        base_query = base_query.where(ConversationMemory.course_id == course_id)

    result = await db.execute(
        base_query.order_by(ConversationMemory.importance.desc()).limit(limit * 2)
    )
    memories = result.scalars().all()

    # Simple keyword scoring
    scored = []
    for mem in memories:
        words = mem.summary.lower().split()
        score = sum(1 for w in search_words if w in words) / max(len(search_words), 1)
        if score > 0:
            scored.append((mem, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [
        {
            "summary": mem.summary,
            "memory_type": mem.memory_type,
            "importance": mem.importance,
            "similarity": score,
            "created_at": mem.created_at.isoformat(),
        }
        for mem, score in scored[:limit]
    ]
