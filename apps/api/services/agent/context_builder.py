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

HISTORY_SUMMARIZE_PROMPT = (
    "Summarize this conversation between a student and tutor. "
    "Preserve: key decisions, learning progress, concepts discussed, "
    "student questions, and any TODOs or follow-ups. "
    "Be concise (under 150 words). Output only the summary."
)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (English ÷4, CJK ÷2)."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return ascii_chars // 4 + non_ascii // 2


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
        client = get_llm_client()
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


async def _trim_context(ctx: AgentContext, db: AsyncSession) -> AgentContext:
    """Trim context to fit token budgets with LLM summarization."""
    # 1. Trim conversation history with summarization
    history_tokens = sum(
        _estimate_tokens(m.get("content", "")) for m in ctx.conversation_history
    )

    if history_tokens > HISTORY_BUDGET and len(ctx.conversation_history) > HISTORY_KEEP_RECENT:
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
        while history_tokens > HISTORY_BUDGET and len(ctx.conversation_history) > 2:
            removed = ctx.conversation_history.pop(0)
            history_tokens -= _estimate_tokens(removed.get("content", ""))

    # 2. Trim RAG docs
    rag_tokens = sum(_estimate_tokens(d.get("content", "")) for d in ctx.content_docs)
    while rag_tokens > RAG_BUDGET and ctx.content_docs:
        removed = ctx.content_docs.pop()
        rag_tokens -= _estimate_tokens(removed.get("content", ""))

    # 3. Trim memories
    mem_tokens = sum(_estimate_tokens(m.get("summary", "")) for m in ctx.memories)
    while mem_tokens > MEMORY_BUDGET and ctx.memories:
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
    from services.memory.pipeline import retrieve_memories
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
        }
        if original_scene == "study_session":
            ctx.scene = scene_policy.scene_id
            ctx.metadata["scene_resolution"] = {
                "scene": scene_policy.scene_id,
                "mode": "policy",
                "matched_text": None,
                "reason": scene_policy.reason,
                "confidence": round(scene_policy.confidence, 3),
            }
        else:
            ctx.metadata["scene_resolution"] = {
                "scene": ctx.scene,
                "mode": "explicit",
                "matched_text": None,
                "reason": "Scene provided by the caller or course context.",
                "policy_recommendation": scene_policy.scene_id,
                "policy_confidence": round(scene_policy.confidence, 3),
            }
        if scene_policy.switch_recommended:
            ctx.metadata.setdefault(
                "scene_switch",
                {
                    "current_scene": original_scene,
                    "target_scene": scene_policy.scene_id,
                    "reason": scene_policy.reason,
                    "policy_confidence": round(scene_policy.confidence, 3),
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
                    return await retrieve_memories(
                        _db, ctx.user_id, ctx.user_message, ctx.course_id, limit=3,
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
            memories = await retrieve_memories(db, ctx.user_id, ctx.user_message, ctx.course_id, limit=3)
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
