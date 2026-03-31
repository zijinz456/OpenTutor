"""Context loading for the orchestrator.

Coordinates parallel/sequential context loading (preferences, memories, RAG)
and delegates to context_sources and context_trimming for implementation details.

Split into:
- context_sources.py — memory recall, topic extraction, history summarization
- context_trimming.py — token budgets, estimation, trimming, compaction guard
"""

import asyncio
import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, IntentType, TaskPhase

# ── Re-exports for backward compatibility ──
from services.agent.context_trimming import (  # noqa: F401
    MEMORY_BUDGET,
    RAG_BUDGET,
    HISTORY_BUDGET,
    HISTORY_KEEP_RECENT,
    INTENT_BUDGET_OVERRIDES,
    HISTORY_SUMMARIZE_PROMPT,
    TOPIC_SUMMARY_PROMPT,
    _estimate_tokens,
    _apply_context_guard,
    _trim_context,
)
from services.agent.context_sources import (  # noqa: F401
    INTENT_MEMORY_TYPES,
    _fetch_latest_by_types,
    _extract_topic_summary,
    _auto_recall_memories,
    _summarize_history,
    _flush_memories_before_trim,
)

logger = logging.getLogger(__name__)


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
            except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:
                logger.exception("Preference loading failed (parallel): %s", exc)
                return None

        async def _load_memories():
            try:
                async with _db_factory() as _db:
                    return await _auto_recall_memories(
                        _db, ctx.user_id, ctx.course_id,
                        ctx.user_message, ctx.conversation_history,
                        limit=5, intent=ctx.intent,
                    )
            except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:
                logger.exception("Memory retrieval failed (parallel): %s", exc)
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
            except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:
                logger.exception("RAG search failed (parallel): %s", exc)
                return None

        pref_result, mem_result, content_result = await asyncio.gather(
            _load_preferences(), _load_memories(), _load_content(),
            return_exceptions=True,
        )

        if isinstance(pref_result, BaseException):
            logger.warning("Preferences load failed: %s", pref_result)
            pref_result = None
        if isinstance(mem_result, BaseException):
            logger.warning("Memories load failed: %s", mem_result)
            mem_result = None
        if isinstance(content_result, BaseException):
            logger.warning("Content load failed: %s", content_result)
            content_result = None

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
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:
            await db.rollback()
            logger.exception("Preference loading failed: %s", exc)

        try:
            memories = await _auto_recall_memories(
                db, ctx.user_id, ctx.course_id,
                ctx.user_message, ctx.conversation_history,
                limit=5, intent=ctx.intent,
            )
            ctx.memories = memories
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:
            await db.rollback()
            logger.exception("Memory retrieval failed: %s", exc)

        try:
            content_docs = await search_content()
            ctx.content_docs = content_docs
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:
            await db.rollback()
            logger.exception("RAG search failed: %s", exc)

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
    except (SQLAlchemyError, ConnectionError, TimeoutError, KeyError) as exc:
        logger.exception("Tutor notes loading failed: %s", exc)

    # Load teaching state for cross-session resumption
    try:
        from services.memory.pipeline import generate_teaching_state, format_resumption_prompt
        teaching_state = await generate_teaching_state(db, ctx.user_id, ctx.course_id)
        if teaching_state:
            ctx.metadata["teaching_state"] = teaching_state
            # Inject resumption prompt when returning after absence
            days = teaching_state.get("days_since_last_session")
            if days is not None and days >= 2:
                ctx.metadata["resumption_prompt"] = format_resumption_prompt(teaching_state)
    except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError) as exc:
        logger.debug("Teaching state loading skipped: %s", exc)

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
    except (SQLAlchemyError, ConnectionError, TimeoutError, AttributeError) as exc:
        logger.exception("Assignment/deadline loading failed: %s", exc)

    # Load teaching strategies (auto-extracted, Claudeception pattern)
    try:
        from services.agent.teaching_strategies import get_teaching_strategies
        strategies = await get_teaching_strategies(db, ctx.user_id, ctx.course_id)
        if strategies:
            ctx.metadata["teaching_strategies"] = strategies
    except (SQLAlchemyError, ConnectionError, TimeoutError, KeyError) as exc:
        logger.exception("Teaching strategies loading failed: %s", exc)

    # Adaptive difficulty guidance for QUIZ intent
    if ctx.intent == IntentType.LEARN:
        try:
            from services.learning_science.difficulty_selector import (
                get_recommendation_for_node,
                format_for_prompt,
            )
            rec = await get_recommendation_for_node(db, ctx.user_id, ctx.course_id)
            ctx.difficulty_guidance = format_for_prompt(rec)
        except (SQLAlchemyError, ConnectionError, TimeoutError, ImportError, ValueError) as exc:
            logger.exception("Difficulty recommendation failed: %s", exc)

    # Phase 4-6: Run independent enrichment tasks concurrently
    async def _load_experiment_config() -> None:
        # Experiment system removed in Phase 1.3
        pass

    async def _load_error_patterns() -> None:
        if ctx.intent != IntentType.LEARN:
            return
        try:
            from services.progress.analytics import get_error_pattern_summary
            error_patterns = await get_error_pattern_summary(db, ctx.user_id, ctx.course_id)
            if error_patterns:
                ctx.metadata["error_patterns"] = error_patterns
                # Feed the most recent error category to the Socratic engine
                if error_patterns:
                    ctx.metadata["last_error_category"] = error_patterns[0].get("category")
        except (SQLAlchemyError, ConnectionError, TimeoutError, ImportError) as exc:
            logger.exception("Error pattern load failed: %s", exc)

    async def _load_cross_course_patterns() -> None:
        if ctx.intent not in (IntentType.LEARN, IntentType.GENERAL, IntentType.PLAN, IntentType.LAYOUT):
            return
        try:
            from services.agent.kv_store import kv_get
            cross_patterns = await kv_get(db, ctx.user_id, "cross_course", "patterns", course_id=None)
            if cross_patterns and isinstance(cross_patterns, dict) and cross_patterns.get("patterns"):
                ctx.metadata["cross_course_patterns"] = cross_patterns["patterns"]
        except (SQLAlchemyError, ConnectionError, TimeoutError, KeyError) as exc:
            logger.exception("Cross-course patterns load failed: %s", exc)

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
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            logger.exception("LaTeX-OCR skipped: %s", exc)

    await asyncio.gather(
        _load_experiment_config(),
        _load_error_patterns(),
        _load_cross_course_patterns(),
        _run_latex_ocr(),
    )

    # Build compact layout context for agent awareness
    block_types = ctx.metadata.get("block_types")
    if block_types:
        dismissed = ctx.metadata.get("dismissed_block_types", [])
        mode = ctx.learning_mode or "unknown"
        parts = [f"Current workspace blocks: {', '.join(block_types)}. Mode: {mode}."]
        if dismissed:
            parts.append(f"Recently dismissed: {', '.join(dismissed)}.")
        ctx.metadata["layout_context"] = " ".join(parts)

    return ctx
