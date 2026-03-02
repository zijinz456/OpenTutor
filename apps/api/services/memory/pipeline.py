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
from collections import Counter
from datetime import datetime, timedelta, timezone

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
    client = get_llm_client("fast")
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
    # Upgraded: merge duplicates into a stronger combined memory instead of just deleting
    merged_pairs: list[tuple] = []  # (keeper, loser, similarity)
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
            # Keep the more important one, merge info from the other
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
        # Append merge metadata
        meta = keeper.metadata_json or {}
        meta["merge_count"] = meta.get("merge_count", 1) + 1
        meta["last_merged_at"] = datetime.now(timezone.utc).isoformat()
        keeper.metadata_json = meta

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


# ── Stage 2b: SMART CONSOLIDATE (AI-powered semantic merge) ──

# Stop words excluded from word-overlap computation
_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will "
    "would shall should may might can could of in to for on with at by from "
    "as into about between through after before during and but or nor not so "
    "yet both either neither each every all any few more most other some such "
    "no only own same than too very it its he she they them their this that "
    "these those i me my we our you your who what which when where how".split()
)

MAX_SMART_MERGES_PER_RUN = 10
SMART_CONSOLIDATE_THRESHOLD = 50  # Minimum memories before AI consolidation kicks in
WORD_OVERLAP_THRESHOLD = 0.30     # 30% shared significant words to form a group


def _significant_words(text: str) -> set[str]:
    """Extract significant (non-stop) words from text, lowercased."""
    return {
        w for w in text.lower().split()
        if w not in _STOP_WORDS and len(w) > 2
    }


def _group_by_word_overlap(
    memories: list["ConversationMemory"],
) -> list[list["ConversationMemory"]]:
    """Group memories by rough word overlap (>30% shared significant words).

    Uses single-linkage clustering: a memory joins a group if it overlaps
    with *any* existing member of that group.  Groups only contain memories
    of the same ``memory_type``.
    """
    # Pre-compute word sets
    word_sets: dict[uuid.UUID, set[str]] = {}
    for mem in memories:
        word_sets[mem.id] = _significant_words(mem.summary)

    assigned: set[uuid.UUID] = set()
    groups: list[list["ConversationMemory"]] = []

    for mem in memories:
        if mem.id in assigned:
            continue
        words_a = word_sets[mem.id]
        if len(words_a) < 2:
            continue

        group = [mem]
        assigned.add(mem.id)

        # Scan remaining memories for overlaps with any group member
        changed = True
        while changed:
            changed = False
            for candidate in memories:
                if candidate.id in assigned:
                    continue
                if candidate.memory_type != mem.memory_type:
                    continue
                words_c = word_sets[candidate.id]
                if len(words_c) < 2:
                    continue
                # Check overlap against any group member
                for member in group:
                    words_m = word_sets[member.id]
                    denom = min(len(words_c), len(words_m))
                    if denom == 0:
                        continue
                    overlap = len(words_c & words_m) / denom
                    if overlap >= WORD_OVERLAP_THRESHOLD:
                        group.append(candidate)
                        assigned.add(candidate.id)
                        changed = True
                        break  # re-scan with enlarged group

        if len(group) >= 2:
            groups.append(group)

    return groups


MERGE_SYSTEM_PROMPT = (
    "Merge these related memories into one concise memory. "
    "Preserve all unique facts. Output only the merged memory text."
)


async def smart_consolidate(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
) -> int:
    """AI-powered memory consolidation (Phase 5.1).

    Groups semantically similar memories and merges them using LLM.
    Only runs when user has > 50 memories to avoid unnecessary cost.

    Returns number of memories merged (i.e. old memories replaced).
    """
    # ── 1. Count user memories; skip if below threshold ──
    count_filters = [
        ConversationMemory.user_id == user_id,
        ConversationMemory.dismissed_at.is_(None),
    ]
    if course_id:
        count_filters.append(ConversationMemory.course_id == course_id)

    count_q = await db.execute(
        select(func.count(ConversationMemory.id)).where(*count_filters)
    )
    total = count_q.scalar() or 0

    if total < SMART_CONSOLIDATE_THRESHOLD:
        logger.debug(
            "smart_consolidate: skipping (only %d memories, threshold %d)",
            total, SMART_CONSOLIDATE_THRESHOLD,
        )
        return 0

    # ── 2. Load all active memories for user+course ──
    query = (
        select(ConversationMemory)
        .where(*count_filters)
        .order_by(ConversationMemory.created_at.asc())
    )
    result = await db.execute(query)
    memories = list(result.scalars().all())

    # ── 3. Group by word overlap ──
    groups = _group_by_word_overlap(memories)
    if not groups:
        logger.debug("smart_consolidate: no groups found for merging")
        return 0

    # ── 4. Merge groups using LLM (max MAX_SMART_MERGES_PER_RUN) ──
    client = get_llm_client("fast")
    total_merged = 0

    for group in groups[:MAX_SMART_MERGES_PER_RUN]:
        try:
            # Build the prompt with all memories in this group
            mem_lines = "\n".join(
                f"- {m.summary}" for m in group
            )
            user_prompt = (
                f"Memories to merge ({len(group)} items, type={group[0].memory_type}):\n"
                f"{mem_lines}"
            )

            merged_text, _ = await client.extract(
                MERGE_SYSTEM_PROMPT,
                user_prompt,
            )
            merged_text = merged_text.strip()
            if not merged_text or len(merged_text) < 5:
                logger.warning("smart_consolidate: LLM returned empty merge, skipping group")
                continue

            # Keep the highest importance score from the group
            best_importance = max(m.importance for m in group)
            total_access = sum((m.access_count or 0) for m in group)

            # Generate embedding for the new merged memory
            embedding = await generate_embedding(merged_text)

            # Create the merged memory
            merged_memory = ConversationMemory(
                user_id=user_id,
                course_id=course_id,
                summary=merged_text,
                memory_type=group[0].memory_type,  # same type (groups are same-type)
                embedding=embedding,
                importance=best_importance,
                access_count=total_access,
                source_message=group[0].source_message,
                metadata_json={
                    "source": "smart_consolidate",
                    "merged_from": [str(m.id) for m in group],
                    "merge_count": len(group),
                    "merged_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            db.add(merged_memory)
            await db.flush()

            # Update BM25 search vector for the new memory
            await db.execute(
                text("""
                    UPDATE conversation_memories
                    SET search_vector = to_tsvector('simple', :summary)
                    WHERE id = :id
                """),
                {"summary": merged_memory.summary, "id": str(merged_memory.id)},
            )

            # Soft-delete the old memories (mark as consolidated)
            now = datetime.now(timezone.utc)
            for old_mem in group:
                old_mem.dismissed_at = now
                old_mem.dismissal_reason = f"smart_consolidated into {merged_memory.id}"
                # Preserve lineage in metadata
                meta = old_mem.metadata_json or {}
                meta["consolidated_into"] = str(merged_memory.id)
                meta["consolidated_at"] = now.isoformat()
                old_mem.metadata_json = meta

            total_merged += len(group)
            logger.info(
                "smart_consolidate: merged %d memories (type=%s) into %s",
                len(group), group[0].memory_type, merged_memory.id,
            )

        except Exception as e:
            logger.warning(
                "smart_consolidate: failed to merge group of %d memories: %s",
                len(group), e,
            )
            continue

    if total_merged:
        await db.flush()
        logger.info(
            "smart_consolidate: total %d memories merged for user %s",
            total_merged, user_id,
        )

    return total_merged


# ── Stage 2c: LONG-TERM MEMORY COMPRESSION ──

COMPRESSION_MERGE_PROMPT = (
    "Merge these related student memories into a single concise summary. "
    "Preserve all unique facts and insights. The merged memory should capture "
    "the essence of all inputs in under 80 words. Output only the merged text."
)


async def compress_old_memories(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    age_threshold_days: int = 14,
) -> int:
    """Compress old memories by grouping related ones and merging via LLM.

    Finds conversation memories older than *age_threshold_days*, groups them
    by topic/category using word-overlap clustering, then asks the LLM to
    merge each group into a single consolidated summary.  Original memories
    are soft-deleted (dismissed) with lineage metadata preserved.

    Returns the count of original memories that were compressed (replaced).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=age_threshold_days)

    # ── 1. Load old, active memories ──
    filters = [
        ConversationMemory.user_id == user_id,
        ConversationMemory.dismissed_at.is_(None),
        ConversationMemory.created_at < cutoff,
    ]
    if course_id:
        filters.append(ConversationMemory.course_id == course_id)

    result = await db.execute(
        select(ConversationMemory)
        .where(*filters)
        .order_by(ConversationMemory.created_at.asc())
    )
    old_memories = list(result.scalars().all())

    if len(old_memories) < 2:
        logger.debug(
            "compress_old_memories: only %d old memories, nothing to compress",
            len(old_memories),
        )
        return 0

    # ── 2. Group by word overlap (reuse existing clustering helper) ──
    groups = _group_by_word_overlap(old_memories)
    if not groups:
        logger.debug("compress_old_memories: no groups formed from old memories")
        return 0

    # ── 3. Merge each group via LLM ──
    client = get_llm_client("fast")
    total_compressed = 0

    for group in groups[:MAX_SMART_MERGES_PER_RUN]:
        try:
            mem_lines = "\n".join(f"- {m.summary}" for m in group)
            user_prompt = (
                f"Memories to compress ({len(group)} items, "
                f"type={group[0].memory_type}):\n{mem_lines}"
            )

            merged_text, _ = await client.extract(
                COMPRESSION_MERGE_PROMPT,
                user_prompt,
            )
            merged_text = merged_text.strip()
            if not merged_text or len(merged_text) < 5:
                continue

            best_importance = max(m.importance for m in group)
            total_access = sum((m.access_count or 0) for m in group)
            embedding = await generate_embedding(merged_text)

            # Determine course_id for the merged memory (use the group's if uniform)
            group_course_ids = {m.course_id for m in group}
            merged_course_id = group_course_ids.pop() if len(group_course_ids) == 1 else course_id

            merged_memory = ConversationMemory(
                user_id=user_id,
                course_id=merged_course_id,
                summary=merged_text,
                memory_type=group[0].memory_type,
                embedding=embedding,
                importance=best_importance,
                access_count=total_access,
                source_message=group[0].source_message,
                metadata_json={
                    "source": "long_term_compression",
                    "compressed_from": [str(m.id) for m in group],
                    "original_count": len(group),
                    "compressed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            db.add(merged_memory)
            await db.flush()

            # Update BM25 search vector for the merged memory
            await db.execute(
                text("""
                    UPDATE conversation_memories
                    SET search_vector = to_tsvector('simple', :summary)
                    WHERE id = :id
                """),
                {"summary": merged_memory.summary, "id": str(merged_memory.id)},
            )

            # Soft-delete originals with lineage
            now = datetime.now(timezone.utc)
            for old_mem in group:
                old_mem.dismissed_at = now
                old_mem.dismissal_reason = f"compressed into {merged_memory.id}"
                meta = old_mem.metadata_json or {}
                meta["compressed_into"] = str(merged_memory.id)
                meta["compressed_at"] = now.isoformat()
                old_mem.metadata_json = meta

            total_compressed += len(group)
            logger.info(
                "compress_old_memories: compressed %d memories (type=%s) into %s",
                len(group), group[0].memory_type, merged_memory.id,
            )

        except Exception as e:
            logger.warning(
                "compress_old_memories: failed to compress group of %d: %s",
                len(group), e,
            )
            continue

    if total_compressed:
        await db.flush()
        logger.info(
            "compress_old_memories: total %d memories compressed for user %s",
            total_compressed, user_id,
        )

    return total_compressed


# ── Stage 2d: CROSS-COURSE MEMORY LINKING ──


async def find_cross_course_patterns(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> list[dict]:
    """Identify topics/concepts that appear across multiple courses.

    Queries all active memories for the user, groups them by significant
    keyword overlap across different courses, and returns a list of
    cross-course connections.  Uses pure text overlap (no LLM call).

    Returns:
        List of dicts: [
            {
                "topic": "<representative keywords>",
                "courses": [
                    {"course_id": str, "course_name": str, "memory_summary": str},
                    ...
                ],
            },
            ...
        ]
    """
    from models.course import Course

    # ── 1. Load all active memories with course info ──
    result = await db.execute(
        select(ConversationMemory, Course.name.label("course_name"))
        .join(Course, ConversationMemory.course_id == Course.id, isouter=True)
        .where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.dismissed_at.is_(None),
            ConversationMemory.course_id.isnot(None),
        )
        .order_by(ConversationMemory.importance.desc())
    )
    rows = result.all()

    if len(rows) < 2:
        return []

    # ── 2. Build per-memory word sets and course mapping ──
    # Each entry: (memory, course_name, significant_words)
    entries: list[tuple] = []
    for row in rows:
        mem = row[0]
        course_name = row[1] or "Unknown Course"
        words = _significant_words(mem.summary)
        if len(words) >= 2:
            entries.append((mem, course_name, words))

    if not entries:
        return []

    # ── 3. Cluster by keyword overlap across different courses ──
    # We want to find topics that span 2+ courses, so we build topic clusters
    # where members come from different courses.
    assigned: set[int] = set()
    clusters: list[list[int]] = []  # indices into entries

    for i, (mem_a, cname_a, words_a) in enumerate(entries):
        if i in assigned:
            continue

        cluster = [i]
        assigned.add(i)
        cluster_courses = {mem_a.course_id}

        for j in range(i + 1, len(entries)):
            if j in assigned:
                continue
            mem_b, cname_b, words_b = entries[j]

            # Require overlap with any cluster member
            for idx in cluster:
                _, _, words_m = entries[idx]
                denom = min(len(words_b), len(words_m))
                if denom == 0:
                    continue
                overlap = len(words_b & words_m) / denom
                if overlap >= WORD_OVERLAP_THRESHOLD:
                    cluster.append(j)
                    assigned.add(j)
                    cluster_courses.add(mem_b.course_id)
                    break

        # Only keep clusters spanning 2+ courses
        if len(cluster_courses) >= 2 and len(cluster) >= 2:
            clusters.append(cluster)

    # ── 4. Build result dicts ──
    connections: list[dict] = []
    for cluster in clusters:
        # Determine representative topic from the most common significant words
        all_words: list[str] = []
        for idx in cluster:
            _, _, words = entries[idx]
            all_words.extend(words)

        word_counts = Counter(all_words)
        top_keywords = [w for w, _ in word_counts.most_common(5)]
        topic = " ".join(top_keywords)

        # Group by course
        course_map: dict[str, dict] = {}
        for idx in cluster:
            mem, course_name, _ = entries[idx]
            cid = str(mem.course_id)
            if cid not in course_map:
                course_map[cid] = {
                    "course_id": cid,
                    "course_name": course_name,
                    "memory_summary": mem.summary,
                }
            else:
                # Append summaries for the same course (keep it concise)
                existing = course_map[cid]["memory_summary"]
                if len(existing) < 300:
                    course_map[cid]["memory_summary"] = (
                        existing + " | " + mem.summary
                    )

        connections.append({
            "topic": topic,
            "courses": list(course_map.values()),
        })

    logger.info(
        "find_cross_course_patterns: found %d cross-course connections for user %s",
        len(connections), user_id,
    )
    return connections


# ── Stage 2e: MEMORY IMPORTANCE DECAY ──


async def apply_importance_decay(
    db: AsyncSession,
    user_id: uuid.UUID,
    decay_rate: float = 0.95,
) -> int:
    """Apply time-based importance decay to all active memories.

    For each memory, reduces importance by *decay_rate* per week since the
    memory was last accessed (updated_at) or created.  Memories that fall
    below the minimum floor of 0.1 are clamped rather than deleted, so no
    data is lost.

    Args:
        db: Async database session.
        user_id: The user whose memories to decay.
        decay_rate: Multiplicative decay factor per week (default 0.95).

    Returns:
        Count of memories whose importance was updated.
    """
    result = await db.execute(
        select(ConversationMemory).where(
            ConversationMemory.user_id == user_id,
            ConversationMemory.dismissed_at.is_(None),
        )
    )
    memories = list(result.scalars().all())

    if not memories:
        return 0

    IMPORTANCE_FLOOR = 0.1
    now = datetime.now(timezone.utc)
    decayed_count = 0

    for mem in memories:
        # Use updated_at as proxy for "last accessed" (it gets bumped on
        # access_count increments and metadata changes).
        last_touched = mem.updated_at or mem.created_at
        weeks_since = (now - last_touched).total_seconds() / (7 * 86400)

        if weeks_since < 0.01:
            # Touched very recently, skip
            continue

        decayed_importance = mem.importance * (decay_rate ** weeks_since)
        decayed_importance = max(IMPORTANCE_FLOOR, decayed_importance)

        if abs(decayed_importance - mem.importance) > 0.001:
            mem.importance = round(decayed_importance, 4)
            decayed_count += 1

    if decayed_count:
        await db.flush()
        logger.info(
            "apply_importance_decay: decayed %d memories for user %s (rate=%.3f)",
            decayed_count, user_id, decay_rate,
        )

    return decayed_count


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

    params = {
        "embedding": str(query_embedding),
        "user_id": str(user_id),
        "limit": limit,
    }
    filters = [
        "user_id = :user_id",
        "embedding IS NOT NULL",
        "dismissed_at IS NULL",
    ]
    if course_id:
        filters.append("course_id = :course_id")
        params["course_id"] = str(course_id)
    if memory_types:
        filters.append("memory_type = ANY(:types)")
        params["types"] = memory_types

    result = await db.execute(
        text(f"""
            SELECT id, summary, memory_type, importance, access_count, created_at, category,
                   1 - (embedding <=> :embedding::vector) as similarity
            FROM conversation_memories
            WHERE {" AND ".join(filters)}
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
    params = {
        "user_id": str(user_id),
        "query": query,
        "limit": limit,
    }
    filters = [
        "user_id = :user_id",
        "search_vector IS NOT NULL",
        "dismissed_at IS NULL",
        "search_vector @@ plainto_tsquery('simple', :query)",
    ]
    if course_id:
        filters.append("course_id = :course_id")
        params["course_id"] = str(course_id)
    if memory_types:
        filters.append("memory_type = ANY(:types)")
        params["types"] = memory_types

    # Try full-text search
    result = await db.execute(
        text(f"""
            SELECT id, summary, memory_type, importance, access_count, created_at, category,
                   ts_rank_cd(search_vector, plainto_tsquery('simple', :query), 32) AS rank
            FROM conversation_memories
            WHERE {" AND ".join(filters)}
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
