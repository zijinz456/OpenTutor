"""Token budget management and context trimming for the orchestrator.

Split from context_builder.py. Handles:
- Token estimation (tiktoken with heuristic fallback)
- Intent-specific token budget configuration
- Per-category context trimming (history, RAG, memories)
- Session-level context window guard (compaction/emergency trim)
"""

import functools
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext

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
    except (ImportError, KeyError, RuntimeError):
        # Fallback: English ~4 chars/token, CJK ~1.5 chars/token
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        non_ascii = len(text) - ascii_chars
        return ascii_chars // 4 + max(1, int(non_ascii / 1.5))


async def _apply_context_guard(ctx: AgentContext) -> AgentContext:
    """Session-level context window guard (OpenFang-inspired).

    Two layers:
    - 70% fill -> LLM-summarise old messages (keep recent N)
    - 90% fill -> Emergency trim (drop oldest messages)

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
        except (ImportError, ConnectionError, RuntimeError):
            logger.debug("Could not get LLM client for context compaction")
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
    from services.agent.context_sources import (
        _flush_memories_before_trim,
        _summarize_history,
    )

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
