"""Memory pipeline: encode → consolidate → retrieve.

Simplified from EverMemOS-style pipeline:
- Rule-based classification into 3 types (profile / knowledge / plan)
- Word overlap + cosine similarity dedup
- Single importance decay rate (90 days for all types)
- BM25 + Vector hybrid retrieval (unchanged)
"""

import logging
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import ConversationMemory
from services.search.compat import update_search_vector

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
    except (ConnectionError, TimeoutError, ValueError, RuntimeError, ImportError, OSError) as exc:
        logger.exception("Embedding generation failed")
        return None


# ── Re-export stages 2 & 3 from pipeline_stages for backward compatibility ──
from .pipeline_stages import (  # noqa: E402
    consolidate_memories,
    retrieve_memories,
    DECAY_HALF_LIFE_DAYS,
    VECTOR_WEIGHT,
    BM25_WEIGHT,
    MIN_SCORE,
)

__all__ = [
    "classify_memory_type",
    "encode_memory",
    "encode_memories",
    "generate_embedding",
    "consolidate_memories",
    "retrieve_memories",
    "DECAY_HALF_LIFE_DAYS",
    "VECTOR_WEIGHT",
    "BM25_WEIGHT",
    "MIN_SCORE",
]
