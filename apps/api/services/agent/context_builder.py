"""Context loading and token-budget trimming for the orchestrator.

Extracted from orchestrator.py. Handles:
- Parallel/sequential context loading (preferences, memories, RAG)
- Token budget management (OpenClaw compaction pattern)
- History summarization with LLM
- Pre-compaction memory flush
"""

import asyncio
import functools
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, IntentType, TaskPhase

logger = logging.getLogger(__name__)

# ── Token budgets for each context category ──
MEMORY_BUDGET = 1500
RAG_BUDGET = 3000
HISTORY_BUDGET = 2000
HISTORY_KEEP_RECENT = 4

# Intent-specific budget overrides: allocate more tokens to what matters most.
# Keys are IntentType values; values override defaults.
INTENT_BUDGET_OVERRIDES: dict[str, dict[str, int]] = {
    "learn": {"RAG_BUDGET": 4000, "MEMORY_BUDGET": 1000, "HISTORY_BUDGET": 1500},
    "review": {"RAG_BUDGET": 2000, "MEMORY_BUDGET": 2500, "HISTORY_BUDGET": 2000},
    "quiz": {"RAG_BUDGET": 3500, "MEMORY_BUDGET": 1000, "HISTORY_BUDGET": 1000},
    "general": {"RAG_BUDGET": 2000, "MEMORY_BUDGET": 1500, "HISTORY_BUDGET": 3000},
    "plan": {"RAG_BUDGET": 2000, "MEMORY_BUDGET": 2000, "HISTORY_BUDGET": 2500},
}

HISTORY_SUMMARIZE_PROMPT = (
    "Summarize this conversation between a student and tutor. "
    "Preserve: key decisions, learning progress, concepts discussed, "
    "student questions, and any TODOs or follow-ups. "
    "Be concise (under 150 words). Output only the summary."
)

TOPIC_SUMMARY_PROMPT = (
    "Extract the main topic or subject being discussed in this recent conversation "
    "between a student and tutor. Output a short phrase (5-15 words) capturing the "
    "core topic. Output only the topic phrase, nothing else."
)


@functools.lru_cache(maxsize=1)
def _get_tiktoken_encoder():
    """Cache the tiktoken encoder to avoid re-loading on every call."""
    import tiktoken
    return tiktoken.get_encoding("cl100k_base")


def _estimate_tokens(text: str) -> int:
    """Token estimate using tiktoken when available, falling back to heuristic."""
    try:
        return len(_get_tiktoken_encoder().encode(text))
    except Exception:
        # Fallback: English ~4 chars/token, CJK ~1.5 chars/token
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii = len(text) - ascii_chars
        return ascii_chars // 4 + max(1, int(non_ascii / 1.5))


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
    from database import is_sqlite

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
            "created_at": row.created_at.isoformat(),
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
    except Exception as e:
        logger.warning("Topic extraction failed: %s", e)

    return None


# Phase 4: Intent-specific memory type priorities for retrieval
INTENT_MEMORY_TYPES: dict[str, list[str] | None] = {
    "review": ["knowledge", "profile"],
    "quiz": ["knowledge"],
    "learn": ["profile", "knowledge"],
    "plan": ["profile", "plan"],
    "general": None,  # No filter, retrieve all types
}


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
    except Exception as e:
        logger.warning("Auto-recall query search failed: %s", e)

    # 2. Always fetch latest profile + preference memories
    try:
        type_results = await _fetch_latest_by_types(
            db, user_id, course_id,
            memory_types=["profile", "preference"],
            limit_per_type=2,
        )
        _add_unique(type_results)
    except Exception as e:
        logger.warning("Auto-recall type fetch failed: %s", e)

    # 3. If conversation history is long, search by topic summary
    if len(conversation_history) > HISTORY_KEEP_RECENT:
        try:
            topic = await _extract_topic_summary(conversation_history)
            if topic and topic != user_message:
                topic_results = await retrieve_memories(
                    db, user_id, topic, course_id, limit=3,
                )
                _add_unique(topic_results)
        except Exception as e:
            logger.warning("Auto-recall topic search failed: %s", e)

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
    except Exception as e:
        logger.warning("History summarization failed: %s", e)

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
    except Exception as e:
        logger.warning("Pre-compaction memory flush failed: %s", e)


async def _apply_context_guard(ctx: AgentContext) -> AgentContext:
    """Session-level context window guard (OpenFang-inspired).

    Two layers:
    - 70% fill → LLM-summarise old messages (keep recent N)
    - 90% fill → Emergency trim (drop oldest messages)

    This runs AFTER per-category _trim_context to handle overall context window pressure.
    """
    from config import settings
    from services.agent.compaction import (
        get_context_window,
        estimate_session_tokens,
        compact_session,
        emergency_trim,
        COMPACTION_TRIGGER_PCT,
        EMERGENCY_TRIM_PCT,
    )

    model_name = settings.llm_model
    context_window = get_context_window(model_name)

    # Build a rough system prompt estimate from context data
    pref_text = " ".join(f"{k}={v}" for k, v in ctx.preferences.items())
    mem_text = " ".join(m.get("summary", "") for m in ctx.memories)
    rag_text = " ".join(d.get("content", "") for d in ctx.content_docs)
    system_estimate = pref_text + mem_text + rag_text

    total_tokens = estimate_session_tokens(
        ctx.conversation_history,
        system_prompt=system_estimate,
    )

    fill_pct = total_tokens / context_window if context_window > 0 else 0.0

    if fill_pct >= EMERGENCY_TRIM_PCT:
        logger.warning(
            "Context guard: emergency trim (%.0f%% of %d window)",
            fill_pct * 100, context_window,
        )
        ctx.conversation_history = emergency_trim(
            ctx.conversation_history, int(context_window * 0.5),
        )
        ctx.metadata["compaction"] = {"action": "emergency_trim", "fill_pct": round(fill_pct, 3)}

    elif fill_pct >= COMPACTION_TRIGGER_PCT:
        logger.info(
            "Context guard: compacting session (%.0f%% of %d window)",
            fill_pct * 100, context_window,
        )
        try:
            from services.llm.router import get_llm_client
            llm_client = get_llm_client("fast")
        except Exception:
            llm_client = None
        ctx.conversation_history, flushed_items = await compact_session(
            ctx.conversation_history, model_name, llm_client,
        )
        ctx.metadata["compaction"] = {"action": "llm_compact", "fill_pct": round(fill_pct, 3)}
        if flushed_items:
            ctx.metadata["memory_flush"] = flushed_items

    return ctx


async def _trim_context(ctx: AgentContext, db: AsyncSession) -> AgentContext:
    """Trim context to fit token budgets with LLM summarization.

    Uses intent-specific budgets: e.g., LEARN intent gets more RAG budget,
    REVIEW intent gets more memory budget, CHAT gets more history budget.
    """
    intent_key = ctx.intent.value if ctx.intent else None
    overrides = INTENT_BUDGET_OVERRIDES.get(intent_key, {}) if intent_key else {}
    history_budget = overrides.get("HISTORY_BUDGET", HISTORY_BUDGET)
    rag_budget = overrides.get("RAG_BUDGET", RAG_BUDGET)
    memory_budget = overrides.get("MEMORY_BUDGET", MEMORY_BUDGET)

    # 1. Trim conversation history with summarization
    history_tokens = sum(
        _estimate_tokens(m.get("content", "")) for m in ctx.conversation_history
    )

    if history_tokens > history_budget and len(ctx.conversation_history) > HISTORY_KEEP_RECENT:
        keep_count = HISTORY_KEEP_RECENT
        messages_to_drop = ctx.conversation_history[:-keep_count]
        messages_to_keep = ctx.conversation_history[-keep_count:]

        await _flush_memories_before_trim(ctx, messages_to_drop, db)
        summary = await _summarize_history(messages_to_drop)

        if summary:
            summary_msg = {
                "role": "system",
                "content": f"[Previous conversation summary] {summary}",
            }
            ctx.conversation_history = [summary_msg] + messages_to_keep
        else:
            ctx.conversation_history = messages_to_keep

        history_tokens = sum(
            _estimate_tokens(m.get("content", "")) for m in ctx.conversation_history
        )
        while history_tokens > history_budget and len(ctx.conversation_history) > 2:
            removed = ctx.conversation_history.pop(0)
            history_tokens -= _estimate_tokens(removed.get("content", ""))

    # 2. Trim RAG docs
    rag_tokens = sum(_estimate_tokens(d.get("content", "")) for d in ctx.content_docs)
    while rag_tokens > rag_budget and ctx.content_docs:
        removed = ctx.content_docs.pop()
        rag_tokens -= _estimate_tokens(removed.get("content", ""))

    # 3. Trim memories
    mem_tokens = sum(_estimate_tokens(m.get("summary", "")) for m in ctx.memories)
    while mem_tokens > memory_budget and ctx.memories:
        removed = ctx.memories.pop()
        mem_tokens -= _estimate_tokens(removed.get("summary", ""))

    return ctx


async def load_context(
    ctx: AgentContext, db: AsyncSession, db_factory=None,
) -> AgentContext:
    """Load preferences, memories, and RAG content into the agent context.

    Uses parallel loading when enabled, sequential otherwise.
    """
    from config import settings
    from database import async_session as _default_db_factory

    ctx.transition(TaskPhase.LOADING_CONTEXT)

    from services.preference.engine import resolve_preferences

    _db_factory = db_factory or _default_db_factory

    # ── Preferences / Memories / RAG — parallel or sequential ──

    if settings.parallel_context_loading and _db_factory is not None:
        async def _load_preferences():
            try:
                async with _db_factory() as _db:
                    resolved = await resolve_preferences(
                        _db, ctx.user_id, ctx.course_id, scene=ctx.scene,
                    )
                    return resolved
            except Exception as exc:
                logger.warning("Preference loading failed (parallel): %s", exc)
                return None

        async def _load_memories():
            try:
                async with _db_factory() as _db:
                    return await _auto_recall_memories(
                        _db, ctx.user_id, ctx.course_id,
                        ctx.user_message, ctx.conversation_history,
                        limit=5, intent=ctx.intent,
                    )
            except Exception as exc:
                logger.warning("Memory retrieval failed (parallel): %s", exc)
                return None

        async def _load_content():
            try:
                async with _db_factory() as _db:
                    if ctx.intent in (IntentType.LEARN, IntentType.GENERAL):
                        from services.search.rag_fusion import rag_fusion_search
                        return await rag_fusion_search(
                            _db, ctx.course_id, ctx.user_message, limit=5,
                        )
                    else:
                        from services.search.hybrid import hybrid_search
                        return await hybrid_search(
                            _db, ctx.course_id, ctx.user_message, limit=5,
                        )
            except Exception as exc:
                logger.warning("RAG search failed (parallel): %s", exc)
                return None

        pref_result, mem_result, content_result = await asyncio.gather(
            _load_preferences(), _load_memories(), _load_content(),
        )

        if pref_result is not None:
            ctx.preferences = pref_result.preferences
            ctx.preference_sources = pref_result.sources
        if mem_result is not None:
            ctx.memories = mem_result
        if content_result is not None:
            ctx.content_docs = content_result

    else:
        # Sequential loading
        async def search_content():
            if ctx.intent in (IntentType.LEARN, IntentType.GENERAL):
                from services.search.rag_fusion import rag_fusion_search
                return await rag_fusion_search(db, ctx.course_id, ctx.user_message, limit=5)
            else:
                from services.search.hybrid import hybrid_search
                return await hybrid_search(db, ctx.course_id, ctx.user_message, limit=5)

        try:
            resolved = await resolve_preferences(db, ctx.user_id, ctx.course_id, scene=ctx.scene)
            ctx.preferences = resolved.preferences
            ctx.preference_sources = resolved.sources
        except Exception as exc:
            await db.rollback()
            logger.warning("Preference loading failed: %s", exc)

        try:
            memories = await _auto_recall_memories(
                db, ctx.user_id, ctx.course_id,
                ctx.user_message, ctx.conversation_history,
                limit=5, intent=ctx.intent,
            )
            ctx.memories = memories
        except Exception as exc:
            await db.rollback()
            logger.warning("Memory retrieval failed: %s", exc)

        try:
            content_docs = await search_content()
            ctx.content_docs = content_docs
        except Exception as exc:
            await db.rollback()
            logger.warning("RAG search failed: %s", exc)

    # Apply context window budget trimming
    ctx = await _trim_context(ctx, db)

    # Session compaction guard (OpenFang-inspired: 70% compact, 90% emergency trim)
    ctx = await _apply_context_guard(ctx)

    # Load tutor notes (lightweight KV read)
    try:
        from services.agent.tutor_notes import get_tutor_notes
        notes = await get_tutor_notes(db, ctx.user_id, ctx.course_id)
        if notes:
            ctx.metadata["tutor_notes"] = notes
    except Exception as exc:
        logger.warning("Tutor notes loading failed: %s", exc)

    # Load upcoming assignments/deadlines for planner context
    try:
        from sqlalchemy import text as sa_text
        result = await db.execute(
            sa_text(
                "SELECT title, due_date, assignment_type, status "
                "FROM assignments WHERE course_id = :course_id AND status = 'active' "
                "ORDER BY due_date ASC LIMIT 20"
            ),
            {"course_id": str(ctx.course_id)} if ctx.course_id else {},
        )
        if ctx.course_id:
            rows = result.fetchall()
            if rows:
                ctx.metadata["assignments"] = [
                    {
                        "title": row.title,
                        "due_date": row.due_date.isoformat() if row.due_date else None,
                        "assignment_type": row.assignment_type,
                        "status": row.status,
                    }
                    for row in rows
                ]
    except Exception as exc:
        logger.warning("Assignment/deadline loading failed: %s", exc)

    # Load teaching strategies (auto-extracted, Claudeception pattern)
    try:
        from services.agent.teaching_strategies import get_teaching_strategies
        strategies = await get_teaching_strategies(db, ctx.user_id, ctx.course_id)
        if strategies:
            ctx.metadata["teaching_strategies"] = strategies
    except Exception as exc:
        logger.warning("Teaching strategies loading failed: %s", exc)

    # Adaptive difficulty guidance for QUIZ intent
    if ctx.intent == IntentType.LEARN:
        try:
            from services.learning_science.difficulty_selector import (
                get_recommendation_for_node,
                format_for_prompt,
            )
            rec = await get_recommendation_for_node(db, ctx.user_id, ctx.course_id)
            ctx.difficulty_guidance = format_for_prompt(rec)
        except Exception as exc:
            logger.warning("Difficulty recommendation failed: %s", exc)

    # Phase 4-6: Run independent enrichment tasks concurrently
    async def _load_experiment_config() -> None:
        # Experiment system removed in Phase 1.3
        pass

    async def _load_error_patterns() -> None:
        if ctx.intent != IntentType.LEARN:
            return
        try:
            from services.progress.tracker import get_error_pattern_summary
            error_patterns = await get_error_pattern_summary(db, ctx.user_id, ctx.course_id)
            if error_patterns:
                ctx.metadata["error_patterns"] = error_patterns
        except Exception as exc:
            logger.debug("Error pattern load failed: %s", exc)

    async def _load_cross_course_patterns() -> None:
        if ctx.intent not in (IntentType.LEARN, IntentType.GENERAL, IntentType.GENERAL, IntentType.PLAN):
            return
        try:
            from services.agent.kv_store import kv_get
            cross_patterns = await kv_get(db, ctx.user_id, "cross_course", "patterns", course_id=None)
            if cross_patterns and isinstance(cross_patterns, dict) and cross_patterns.get("patterns"):
                ctx.metadata["cross_course_patterns"] = cross_patterns["patterns"]
        except Exception as exc:
            logger.debug("Cross-course patterns load failed: %s", exc)

    async def _run_latex_ocr() -> None:
        if not ctx.images:
            return
        try:
            from services.vision.latex_ocr import try_extract_latex
            latex_results = await asyncio.to_thread(try_extract_latex, ctx.images)
            if latex_results:
                latex_text = "\n".join(f"$${l}$$" for l in latex_results)
                ctx.user_message = (
                    f"{ctx.user_message}\n\n"
                    f"[Extracted LaTeX from attached image(s):\n{latex_text}]"
                )
                ctx.metadata["latex_ocr"] = latex_results
                logger.info("LaTeX-OCR extracted %d formula(s)", len(latex_results))
        except Exception as exc:
            logger.debug("LaTeX-OCR skipped: %s", exc)

    async def _load_screen_context() -> None:
        try:
            from services.context.screen import get_screen_context_service
            screen_svc = get_screen_context_service()
            if screen_svc.is_enabled:
                screen_ctx = await screen_svc.get_study_context(minutes=10)
                if screen_ctx:
                    ctx.metadata["screen_context"] = screen_ctx
                    topic_hint = screen_ctx.get("study_topic_hint")
                    if topic_hint:
                        ctx.metadata["screen_topic_hint"] = topic_hint
                    logger.info("Screenpipe context loaded: apps=%s, topic=%s",
                                screen_ctx.get("app_names", []), topic_hint)
        except Exception as exc:
            logger.debug("Screenpipe context skipped: %s", exc)

    await asyncio.gather(
        _load_experiment_config(),
        _load_error_patterns(),
        _load_cross_course_patterns(),
        _run_latex_ocr(),
        _load_screen_context(),
    )

    return ctx
