"""MemoryConsolidationAgent — background agent for memory maintenance.

Borrows from:
- OpenClaw Memory Flush: auto-flush to persistent storage near context limits
- OpenAkita consolidation: periodic dedup + decay routines
- memU layer hierarchy: Resource → Item → Category organization
- EverMemOS MemCell: atomic memory lifecycle management

Runs as a background task (OpenClaw Queue Lane: cron lane) for:
1. Real-time Flush: save important memories during long sessions
2. Periodic Consolidation: dedup + decay + categorize
3. FSRS Decay: update spaced repetition scores
"""

import logging
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.memory import ConversationMemory
from services.memory.pipeline import consolidate_memories
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

    client = get_llm_client()
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

    except Exception as e:
        logger.warning("Memory categorization failed: %s", e)
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

    # Step 3: Collect stats
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
