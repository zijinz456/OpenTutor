"""Context loading and token-budget trimming for the orchestrator.

Extracted from orchestrator.py. Handles:
- Parallel/sequential context loading (preferences, memories, RAG)
- Token budget management (OpenClaw compaction pattern)
- History summarization with LLM
- Pre-compaction memory flush
"""

import asyncio
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
    "chat": {"RAG_BUDGET": 2000, "MEMORY_BUDGET": 1500, "HISTORY_BUDGET": 3000},
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


def _estimate_tokens(text: str) -> int:
    """Token estimate using tiktoken when available, falling back to heuristic."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
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
    """
    from sqlalchemy import text as sa_text

    results = []
    for mem_type in memory_types:
        params = {
            "user_id": str(user_id),
            "memory_type": mem_type,
            "limit": limit_per_type,
        }
        filters = [
            "user_id = :user_id",
            "memory_type = :memory_type",
            "dismissed_at IS NULL",
        ]
        if course_id:
            filters.append("(course_id = :course_id OR course_id IS NULL)")
            params["course_id"] = str(course_id)

        rows = await db.execute(
            sa_text(f"""
                SELECT id, summary, memory_type, importance, access_count,
                       created_at, category
                FROM conversation_memories
                WHERE {" AND ".join(filters)}
                ORDER BY importance DESC, created_at DESC
                LIMIT :limit
            """),
            params,
        )
        for row in rows.fetchall():
            results.append({
                "id": str(row.id),
                "summary": row.summary,
                "memory_type": row.memory_type,
                "importance": row.importance,
                "category": row.category,
                "created_at": row.created_at.isoformat(),
                "source": "auto_recall",
            })
    return results


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


async def _auto_recall_memories(
    db: AsyncSession,
    user_id,
    course_id,
    user_message: str,
    conversation_history: list[dict],
    limit: int = 5,
) -> list[dict]:
    """Enhanced memory recall with multi-strategy retrieval.

    Strategy:
    1. Search with user message (existing semantic/BM25 hybrid search)
    2. Always fetch latest profile/preference memories for user+course
    3. If conversation is long (> 4 messages), also search by topic summary
    4. Deduplicate results by memory ID
    """
    from services.memory.pipeline import retrieve_memories

    seen_ids: set[str] = set()
    all_memories: list[dict] = []

    def _add_unique(mems: list[dict]):
        for m in mems:
            mid = m.get("id")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_memories.append(m)

    # 1. Primary search: user message query (existing behavior)
    try:
        query_results = await retrieve_memories(
            db, user_id, user_message, course_id, limit=limit,
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
        ctx.conversation_history = await compact_session(
            ctx.conversation_history, model_name, llm_client,
        )
        ctx.metadata["compaction"] = {"action": "llm_compact", "fill_pct": round(fill_pct, 3)}

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
    from services.scene.policy import resolve_scene_policy

    _db_factory = db_factory or _default_db_factory

    # ── Scene policy (always sequential — mutates ctx.scene early) ──
    original_scene = ctx.scene
    try:
        scene_policy = await resolve_scene_policy(
            db,
            user_id=ctx.user_id,
            course_id=ctx.course_id,
            message=ctx.user_message,
            current_scene=original_scene,
            active_tab=ctx.active_tab,
        )
        ctx.metadata["scene_policy"] = {
            "recommended_scene": scene_policy.scene_id,
            "confidence": round(scene_policy.confidence, 3),
            "scores": scene_policy.scores,
            "features": scene_policy.features,
            "reason": scene_policy.reason,
            "switch_recommended": scene_policy.switch_recommended,
            "expected_benefit": scene_policy.expected_benefit,
            "reversible_action": scene_policy.reversible_action,
            "layout_policy": scene_policy.layout_policy,
            "reasoning_policy": scene_policy.reasoning_policy,
            "workflow_policy": scene_policy.workflow_policy,
        }
        if original_scene == "study_session":
            ctx.scene = scene_policy.scene_id
            ctx.metadata["scene_resolution"] = {
                "scene": scene_policy.scene_id,
                "mode": "policy",
                "matched_text": None,
                "reason": scene_policy.reason,
                "confidence": round(scene_policy.confidence, 3),
                "expected_benefit": scene_policy.expected_benefit,
                "layout_policy": scene_policy.layout_policy,
                "reasoning_policy": scene_policy.reasoning_policy,
                "workflow_policy": scene_policy.workflow_policy,
            }
        else:
            ctx.metadata["scene_resolution"] = {
                "scene": ctx.scene,
                "mode": "explicit",
                "matched_text": None,
                "reason": "Scene provided by the caller or course context.",
                "policy_recommendation": scene_policy.scene_id,
                "policy_confidence": round(scene_policy.confidence, 3),
                "expected_benefit": scene_policy.expected_benefit,
                "layout_policy": scene_policy.layout_policy,
                "reasoning_policy": scene_policy.reasoning_policy,
                "workflow_policy": scene_policy.workflow_policy,
            }
        if scene_policy.switch_recommended:
            ctx.metadata.setdefault(
                "scene_switch",
                {
                    "current_scene": original_scene,
                    "target_scene": scene_policy.scene_id,
                    "reason": scene_policy.reason,
                    "policy_confidence": round(scene_policy.confidence, 3),
                    "expected_benefit": scene_policy.expected_benefit,
                    "reversible_action": scene_policy.reversible_action,
                },
            )
    except Exception as exc:
        await db.rollback()
        logger.warning("Scene policy resolution failed: %s", exc)
        ctx.metadata["scene_resolution"] = {
            "scene": ctx.scene,
            "mode": "fallback",
            "matched_text": None,
            "reason": "Scene policy unavailable; keeping current scene.",
        }

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
                        limit=5,
                    )
            except Exception as exc:
                logger.warning("Memory retrieval failed (parallel): %s", exc)
                return None

        async def _load_content():
            try:
                async with _db_factory() as _db:
                    if ctx.intent in (IntentType.LEARN, IntentType.REVIEW):
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
            if ctx.intent in (IntentType.LEARN, IntentType.REVIEW):
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
                limit=5,
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

    # Adaptive difficulty guidance for QUIZ intent
    if ctx.intent == IntentType.QUIZ:
        try:
            from services.learning_science.difficulty_selector import (
                get_recommendation_for_node,
                format_for_prompt,
            )
            rec = await get_recommendation_for_node(db, ctx.user_id, ctx.course_id)
            ctx.difficulty_guidance = format_for_prompt(rec)
        except Exception as exc:
            logger.warning("Difficulty recommendation failed: %s", exc)

    return ctx
