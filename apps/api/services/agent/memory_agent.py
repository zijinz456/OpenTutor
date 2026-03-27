"""MemoryConsolidationAgent — background agent for memory maintenance.

Borrows from:
- OpenClaw Memory Flush: auto-flush to persistent storage near context limits
- OpenAkita consolidation: periodic dedup + decay routines
- memU layer hierarchy: Resource → Item → Category organization
- EverMemOS MemCell: atomic memory lifecycle management

Runs as a background task (OpenClaw Queue Lane: cron lane) for:
1. Real-time Flush: save important memories during long sessions
2. Periodic Consolidation: dedup + decay + categorize + merge
3. Session Episodic Summary: create session-level episode memories
4. Auto-consolidation: trigger after every N messages
"""

import json
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select, func, case, literal_column
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import ConversationMemory, MEMCELL_TYPES
from services.memory.pipeline import consolidate_memories, generate_embedding
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


# ── Memory Flush (OpenClaw pattern) ──

async def flush_session_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    conversation_summary: str,
) -> dict:
    """Flush important memories from a long session to persistent storage.

    Triggered when context window approaches limit (OpenClaw compaction pattern).
    Extracts key learnings from the conversation summary and stores as MemCells.
    """
    from services.memory.pipeline import encode_memory

    result = await encode_memory(
        db, user_id, course_id,
        user_message=f"[Session Summary] {conversation_summary[:500]}",
        assistant_response="[Auto-flush] Consolidating session learnings.",
    )
    await db.commit()
    return {"flushed": len(result)}


# ── Categorization (memU pattern) ──

CATEGORIZE_PROMPT = """Given these uncategorized memory entries for a student, assign each a category.

Categories should be course topics or learning themes, e.g.:
- "Linear Algebra / Eigenvalues"
- "Calculus / Limits"
- "Study Habits"
- "Error Patterns"

Memories:
{memories}

Output JSON array: [{{"id": "<memory_id>", "category": "<category>"}}]
Only categorize memories that clearly belong to a topic. Skip ambiguous ones."""


async def categorize_uncategorized(
    db: AsyncSession,
    user_id: uuid.UUID,
    batch_size: int = 20,
) -> dict:
    """Assign categories to uncategorized memories (memU 3-layer pattern).

    Runs periodically to organize flat memories into a hierarchy.
    """
    result = await db.execute(
        select(ConversationMemory)
        .where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.category.is_(None),
        )
        .order_by(ConversationMemory.created_at.desc())
        .limit(batch_size)
    )
    memories = list(result.scalars().all())

    if not memories:
        return {"categorized": 0}

    # Build memory text for LLM
    mem_text = "\n".join(
        f'- id="{m.id}" type={m.memory_type}: {m.summary[:100]}'
        for m in memories
    )

    client = get_llm_client("fast")
    try:
        response, _ = await client.extract(
            "You are a memory organizer. Output valid JSON array.",
            CATEGORIZE_PROMPT.format(memories=mem_text),
        )
        response = response.strip()
        if "```" in response:
            json_start = response.find("[")
            json_end = response.rfind("]") + 1
            if json_start >= 0 and json_end > json_start:
                response = response[json_start:json_end]

        import json
        categories = json.loads(response)
        if not isinstance(categories, list):
            return {"categorized": 0}

        # Apply categories
        mem_map = {str(m.id): m for m in memories}
        categorized = 0
        for item in categories:
            mem_id = item.get("id")
            category = item.get("category", "").strip()
            if mem_id in mem_map and category:
                mem_map[mem_id].category = category[:100]
                categorized += 1

        if categorized:
            await db.flush()
        return {"categorized": categorized}

    except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError, json.JSONDecodeError, RuntimeError) as e:
        logger.exception("Memory categorization failed: %s", e)
        return {"categorized": 0}


# ── Full Consolidation Pipeline ──

async def run_full_consolidation(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Run the full memory consolidation pipeline.

    Combines:
    1. Deduplication + decay (EverMemOS + OpenAkita)
    2. Categorization (memU)
    3. Stats collection

    Intended to run as a cron job (OpenClaw cron lane).
    """
    # Step 1: Consolidate (dedup + decay)
    consolidation_result = await consolidate_memories(db, user_id, course_id)

    # Step 2: Categorize uncategorized
    categorization_result = await categorize_uncategorized(db, user_id)

    # Step 4: Collect stats
    count_result = await db.execute(
        select(func.count(ConversationMemory.id))
        .where(ConversationMemory.user_id == user_id)
    )
    total_memories = count_result.scalar() or 0

    await db.commit()

    return {
        **consolidation_result,
        **categorization_result,
        "total_memories": total_memories,
    }


# ── Session Episodic Summary ──

SESSION_SUMMARY_PROMPT = """Summarize this learning session into a single episodic memory.

Focus on:
- What topics were covered
- Key breakthroughs or struggles
- Overall session quality and student engagement

Session messages (last {count} exchanges):
{messages}

Output a single paragraph (50-100 words) capturing the essence of this session.
If the session is too trivial (e.g., just greetings), return NONE."""


async def create_session_episodic_memory(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    session_messages: list[dict],
) -> ConversationMemory | None:
    """Create a session-level episodic memory summarizing an entire learning session.

    Called when a chat session ends or when the user starts a new session.
    This creates a high-level "episode" memory that captures the full session context,
    complementing the atomic MemCells extracted per turn.
    """
    if len(session_messages) < 4:  # Need at least 2 exchanges
        return None

    # Build message text
    msg_text = "\n".join(
        f"{'Student' if m.get('role') == 'user' else 'Tutor'}: {m.get('content', '')[:200]}"
        for m in session_messages[-20:]  # Last 20 messages max
    )

    client = get_llm_client("fast")
    try:
        result, _ = await client.extract(
            "You are a learning session summarizer. Output a brief summary or NONE.",
            SESSION_SUMMARY_PROMPT.format(count=len(session_messages), messages=msg_text),
        )
        result = result.strip()
        if not result or result.upper().startswith("NONE"):
            return None

        embedding = await generate_embedding(result)
        memory = ConversationMemory(
            user_id=user_id,
            course_id=course_id,
            summary=result,
            memory_type="knowledge",
            embedding=embedding,
            importance=0.7,  # Episodes are high-value
            source_message=f"[Session: {len(session_messages)} messages]",
            metadata_json={
                "source": "session_episodic",
                "message_count": len(session_messages),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.add(memory)
        await db.flush()

        # Update BM25 search vector
        from services.search.compat import update_search_vector
        await update_search_vector(db, "conversation_memories", str(memory.id), memory.summary)
        await db.flush()
        logger.info("Session episodic memory created for user %s", user_id)
        return memory

    except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        logger.exception("Session episodic summary failed: %s", e)
        return None


# ── Memory Statistics ──

async def get_memory_stats(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Get memory health statistics for the analytics dashboard.

    Returns type distribution, age stats, importance distribution,
    and consolidation health indicators.
    """
    base_filter = [ConversationMemory.user_id == user_id]
    if course_id:
        base_filter.append(ConversationMemory.course_id == course_id)

    # Total count
    total_q = await db.execute(
        select(func.count(ConversationMemory.id)).where(*base_filter)
    )
    total = total_q.scalar() or 0

    if total == 0:
        return {
            "total": 0,
            "by_type": {},
            "avg_importance": 0,
            "needs_consolidation": False,
            "oldest_days": 0,
            "uncategorized": 0,
            "merged_count": 0,
        }

    # Count by type
    type_q = await db.execute(
        select(ConversationMemory.memory_type, func.count(ConversationMemory.id))
        .where(*base_filter)
        .group_by(ConversationMemory.memory_type)
    )
    by_type = {row[0]: row[1] for row in type_q.fetchall()}

    # Average importance
    imp_q = await db.execute(
        select(func.avg(ConversationMemory.importance)).where(*base_filter)
    )
    avg_importance = round(float(imp_q.scalar() or 0), 3)

    # Uncategorized count
    uncat_q = await db.execute(
        select(func.count(ConversationMemory.id))
        .where(*base_filter, ConversationMemory.category.is_(None))
    )
    uncategorized = uncat_q.scalar() or 0

    # Oldest memory age in days
    oldest_q = await db.execute(
        select(func.min(ConversationMemory.created_at)).where(*base_filter)
    )
    oldest = oldest_q.scalar()
    now = datetime.now(timezone.utc)
    if oldest:
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)
        oldest_days = int((now - oldest).total_seconds() / 86400)
    else:
        oldest_days = 0

    # Merged memories count (those with merge_count > 1 in metadata)
    # We can approximate from metadata_json but for now count all
    all_mems_q = await db.execute(
        select(ConversationMemory.metadata_json)
        .where(*base_filter)
        .where(ConversationMemory.metadata_json.isnot(None))
    )
    merged_count = sum(
        1 for row in all_mems_q.scalars().all()
        if isinstance(row, dict) and row.get("merge_count", 1) > 1
    )

    # Consolidation health: suggest if > 100 memories or > 30% uncategorized
    needs_consolidation = total > 100 or (uncategorized / total > 0.3 if total else False)

    return {
        "total": total,
        "by_type": by_type,
        "avg_importance": avg_importance,
        "needs_consolidation": needs_consolidation,
        "oldest_days": oldest_days,
        "uncategorized": uncategorized,
        "merged_count": merged_count,
    }


# ── Auto-consolidation Trigger ──

# Track message counts per user to trigger consolidation
_message_counters: dict[str, int] = {}
AUTO_CONSOLIDATE_EVERY = 20  # Run consolidation every N messages


async def maybe_auto_consolidate(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> dict | None:
    """Check if auto-consolidation should run based on message count.

    Called during post-processing. Returns consolidation results if triggered,
    None otherwise.
    """
    key = str(user_id)
    _message_counters[key] = _message_counters.get(key, 0) + 1

    if _message_counters[key] >= AUTO_CONSOLIDATE_EVERY:
        _message_counters[key] = 0
        logger.info("Auto-consolidation triggered for user %s (every %d messages)", user_id, AUTO_CONSOLIDATE_EVERY)
        result = await run_full_consolidation(db, user_id, course_id)
        return result

    return None
