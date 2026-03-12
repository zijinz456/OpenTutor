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

try:
    from openai import OpenAIError
except ImportError:  # pragma: no cover - openai is a core dependency in normal runtime
    OpenAIError = RuntimeError

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
        from services.embedding.registry import get_embedding_provider, is_noop_provider
        if is_noop_provider():
            return None  # Don't store useless zero vectors
        provider = get_embedding_provider()
        return await provider.embed(text_content)
    except (ConnectionError, TimeoutError, ValueError, RuntimeError, ImportError, OSError, OpenAIError) as exc:
        logger.exception("Embedding generation failed")
        return None


# ── Re-export stages 2 & 3 from pipeline_stages for backward compatibility ──
from .pipeline_stages import (  # noqa: E402
    consolidate_memories,
    retrieve_memories,
    DECAY_HALF_LIFE_DAYS,
    VECTOR_WEIGHT,
    BM25_WEIGHT,
    RRF_MIN_SCORE,
)

MIN_SCORE = RRF_MIN_SCORE  # backward compat alias


# ── Teaching State Summary ──


async def generate_teaching_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict | None:
    """Generate a structured teaching state for cross-session continuity.

    Returns a dict with strengths, weaknesses, active topic, next topic,
    days since last session, mastery summary, and review urgency.
    Returns None if the course has no knowledge graph yet.
    """
    from datetime import datetime, timezone

    try:
        from services.loom_graph import get_mastery_graph
        graph = await get_mastery_graph(db, user_id, course_id)
        if not graph or not graph.get("nodes"):
            return None

        nodes = graph["nodes"]
        weak = graph.get("weak_concepts", [])
        next_topic = graph.get("next_to_study")

        # Compute mastery summary
        masteries = [n.get("mastery", 0.0) for n in nodes]
        avg_mastery = sum(masteries) / len(masteries) if masteries else 0.0
        mastered_count = sum(1 for m in masteries if m >= 0.8)
        total_count = len(masteries)

        # Get LECTOR review urgency
        review_urgency = 0
        try:
            from services.lector import get_review_summary
            review_summary = await get_review_summary(db, user_id, course_id)
            review_urgency = review_summary.get("urgent_count", 0)
        except (ImportError, KeyError, TypeError, AttributeError):
            logger.debug("LECTOR review summary unavailable", exc_info=True)

        # Get last session time
        days_since_last = None
        try:
            from sqlalchemy import select as sa_select, func as sa_func
            from models.chat_session import ChatSession
            last_result = await db.execute(
                sa_select(sa_func.max(ChatSession.updated_at)).where(
                    ChatSession.user_id == user_id,
                    ChatSession.course_id == course_id,
                )
            )
            last_time = last_result.scalar()
            if last_time:
                if last_time.tzinfo is None:
                    last_time = last_time.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - last_time
                days_since_last = delta.days
        except (ImportError, ValueError, AttributeError):
            logger.debug("Last session time unavailable", exc_info=True)

        # Top strengths
        sorted_nodes = sorted(nodes, key=lambda n: n.get("mastery", 0), reverse=True)
        strengths = [n["name"] for n in sorted_nodes[:3] if n.get("mastery", 0) >= 0.6]

        return {
            "strengths": strengths,
            "weaknesses": weak[:5],
            "next_topic": next_topic,
            "days_since_last_session": days_since_last,
            "avg_mastery": round(avg_mastery, 3),
            "mastered_count": mastered_count,
            "total_concepts": total_count,
            "review_urgency": review_urgency,
        }
    except Exception:
        logger.warning("Teaching state generation failed", exc_info=True)
        return None


def format_resumption_prompt(state: dict) -> str:
    """Format teaching state into a natural resumption prompt for the agent."""
    parts = []
    days = state.get("days_since_last_session")
    if days is not None and days >= 1:
        parts.append(f"The student last studied {days} day(s) ago.")

    avg = state.get("avg_mastery", 0)
    mastered = state.get("mastered_count", 0)
    total = state.get("total_concepts", 0)
    if total > 0:
        parts.append(f"Overall mastery: {avg:.0%} ({mastered}/{total} concepts mastered).")

    strengths = state.get("strengths", [])
    if strengths:
        parts.append(f"Strengths: {', '.join(strengths)}.")

    weaknesses = state.get("weaknesses", [])
    if weaknesses:
        parts.append(f"Areas needing work: {', '.join(weaknesses)}.")

    urgency = state.get("review_urgency", 0)
    if urgency >= 3:
        parts.append(f"{urgency} concepts at risk of being forgotten — prioritize review.")

    next_topic = state.get("next_topic")
    if next_topic:
        parts.append(f"Recommended next topic: {next_topic}.")

    return " ".join(parts)


# Re-export from pipeline_stages (extracted for single-concern files)
from services.memory.pipeline_stages import (  # noqa: E402
    consolidate_memories,
    retrieve_memories,
)

# Alias for the typo in progress_analytics (consolidate_memory → consolidate_memories)
consolidate_memory = consolidate_memories

__all__ = [
    "classify_memory_type",
    "encode_memory",
    "encode_memories",
    "generate_embedding",
    "consolidate_memories",
    "consolidate_memory",
    "retrieve_memories",
    "generate_teaching_state",
    "format_resumption_prompt",
    "DECAY_HALF_LIFE_DAYS",
    "VECTOR_WEIGHT",
    "BM25_WEIGHT",
    "MIN_SCORE",
]
