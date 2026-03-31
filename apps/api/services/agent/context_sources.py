"""Context source implementations: memory recall, topic extraction, history summarization.

Split from context_builder.py. Handles:
- Multi-strategy memory recall (semantic search, profile/preference, topic-based)
- Topic extraction from conversation history
- History summarization via LLM
- Pre-compaction memory flush
"""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.context_trimming import (
    HISTORY_BUDGET,
    HISTORY_KEEP_RECENT,
    TOPIC_SUMMARY_PROMPT,
    HISTORY_SUMMARIZE_PROMPT,
    _estimate_tokens,
)
from services.agent.state import AgentContext

logger = logging.getLogger(__name__)


# Phase 4: Intent-specific memory type priorities for retrieval
INTENT_MEMORY_TYPES: dict[str, list[str] | None] = {
    "review": ["knowledge", "profile"],
    "quiz": ["knowledge"],
    "learn": ["profile", "knowledge"],
    "plan": ["profile", "plan"],
    "general": None,  # No filter, retrieve all types
}


async def _fetch_latest_by_types(
    db: AsyncSession,
    user_id,
    course_id,
    memory_types: list[str],
    limit_per_type: int = 2,
) -> list[dict]:
    """Fetch the latest memories of specific types for a user+course, regardless of query.

    This ensures profile and preference memories are always included in context,
    even if they don't match the current search query.

    Uses a single query with ROW_NUMBER() window function instead of one query
    per memory type.
    """
    from sqlalchemy import text as sa_text

    if not memory_types:
        return []

    params: dict = {
        "user_id": str(user_id),
        "limit_per_type": limit_per_type,
    }
    course_filter = "AND (course_id = :course_id OR course_id IS NULL)" if course_id else ""
    if course_id:
        params["course_id"] = str(course_id)

    # Build memory_type filter (PG uses ANY, SQLite uses IN)
    type_placeholders = ", ".join(f":mt{i}" for i in range(len(memory_types)))
    for i, mt in enumerate(memory_types):
        params[f"mt{i}"] = mt
    type_filter = f"memory_type IN ({type_placeholders})"

    rows = await db.execute(
        sa_text(f"""
            SELECT id, summary, memory_type, importance, category, created_at
            FROM (
                SELECT id, summary, memory_type, importance, category, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY memory_type
                           ORDER BY importance DESC, created_at DESC
                       ) AS rn
                FROM conversation_memories
                WHERE user_id = :user_id
                  AND {type_filter}
                  AND dismissed_at IS NULL
                  {course_filter}
            ) sub
            WHERE rn <= :limit_per_type
        """),
        params,
    )
    return [
        {
            "id": str(row.id),
            "summary": row.summary,
            "memory_type": row.memory_type,
            "importance": row.importance,
            "category": row.category,
            "created_at": row.created_at if isinstance(row.created_at, str) else row.created_at.isoformat(),
            "source": "auto_recall",
        }
        for row in rows.fetchall()
    ]


async def _extract_topic_summary(messages: list[dict]) -> str | None:
    """Extract a short topic phrase from recent conversation history."""
    parts = []
    for msg in messages[-6:]:  # Look at last 6 messages
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not content or role == "system":
            continue
        parts.append(f"{role}: {content[:200]}")

    if not parts:
        return None

    try:
        from services.llm.router import get_llm_client
        client = get_llm_client("fast")
        topic, _ = await client.extract(
            "You extract conversation topics concisely.",
            f"{TOPIC_SUMMARY_PROMPT}\n\nConversation:\n" + "\n".join(parts),
        )
        topic = topic.strip()
        if topic and len(topic) > 3:
            return topic
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        # Best-effort: topic extraction is non-critical enrichment
        logger.warning("Topic extraction failed: %s", e)

    return None


async def _auto_recall_memories(
    db: AsyncSession,
    user_id,
    course_id,
    user_message: str,
    conversation_history: list[dict],
    limit: int = 5,
    intent=None,
) -> list[dict]:
    """Enhanced memory recall with multi-strategy retrieval.

    Strategy:
    1. Search with user message (existing semantic/BM25 hybrid search)
    2. Always fetch latest profile/preference memories for user+course
    3. If conversation is long (> 4 messages), also search by topic summary
    4. Deduplicate results by memory ID

    Phase 4: Intent-aware memory type filtering — REVIEW prioritizes error/skill,
    QUIZ prioritizes knowledge/error, etc.
    """
    from services.memory.pipeline import retrieve_memories

    # Resolve intent-specific memory types
    intent_key = intent.value if intent else "general"
    memory_types = INTENT_MEMORY_TYPES.get(intent_key)

    seen_ids: set[str] = set()
    all_memories: list[dict] = []

    def _add_unique(mems: list[dict]):
        for m in mems:
            mid = m.get("id")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_memories.append(m)

    # 1. Primary search: user message query with intent-aware type filtering
    try:
        query_results = await retrieve_memories(
            db, user_id, user_message, course_id, limit=limit,
            memory_types=memory_types,
        )
        _add_unique(query_results)
    except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as e:
        logger.exception("Auto-recall query search failed: %s", e)

    # 2. Always fetch latest profile + preference memories
    try:
        type_results = await _fetch_latest_by_types(
            db, user_id, course_id,
            memory_types=["profile", "preference"],
            limit_per_type=2,
        )
        _add_unique(type_results)
    except (SQLAlchemyError, ConnectionError, TimeoutError) as e:
        logger.exception("Auto-recall type fetch failed: %s", e)

    # 3. If conversation history is long, search by topic summary
    if len(conversation_history) > HISTORY_KEEP_RECENT:
        try:
            topic = await _extract_topic_summary(conversation_history)
            if topic and topic != user_message:
                topic_results = await retrieve_memories(
                    db, user_id, topic, course_id, limit=3,
                )
                _add_unique(topic_results)
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as e:
            logger.exception("Auto-recall topic search failed: %s", e)

    return all_memories


async def _summarize_history(messages: list[dict]) -> str | None:
    """Summarize conversation history using a lightweight LLM call."""
    if not messages:
        return None

    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if not content:
            continue
        if _estimate_tokens(content) > HISTORY_BUDGET // 2:
            content = content[:800] + " [truncated]"
        parts.append(f"{role}: {content}")

    if not parts:
        return None

    conversation_text = "\n".join(parts)

    try:
        from services.llm.router import get_llm_client
        client = get_llm_client("fast")
        summary, _ = await client.extract(
            "You are a conversation summarizer for an educational tutoring system.",
            f"{HISTORY_SUMMARIZE_PROMPT}\n\nConversation:\n{conversation_text}",
        )
        summary = summary.strip()
        if summary and len(summary) > 10:
            return summary
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        logger.exception("History summarization failed: %s", e)

    return None


async def _flush_memories_before_trim(
    ctx: AgentContext,
    messages_to_drop: list[dict],
    db: AsyncSession,
) -> None:
    """Pre-compaction memory flush: encode memories from messages about to be trimmed."""
    if not messages_to_drop or ctx.metadata.get("memory_flushed"):
        return

    user_parts = []
    assistant_parts = []
    for msg in messages_to_drop:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "user":
            user_parts.append(content[:300])
        elif role == "assistant":
            assistant_parts.append(content[:300])

    if not user_parts and not assistant_parts:
        return

    try:
        from services.memory.pipeline import encode_memory
        await encode_memory(
            db,
            ctx.user_id,
            ctx.course_id,
            user_message="\n".join(user_parts),
            assistant_response="\n".join(assistant_parts),
        )
        ctx.metadata["memory_flushed"] = True
        logger.info("Pre-compaction memory flush completed for user %s", ctx.user_id)
    except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        logger.exception("Pre-compaction memory flush failed: %s", e)
