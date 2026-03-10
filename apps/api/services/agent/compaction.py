"""Token-aware session compaction and context window management.

Inspired by OpenFang's two-layer context budget system:
- Layer 1: Per-result truncation (handled by existing ToolResult.truncated())
- Layer 2: Session compaction when context window fills up

Strategies:
- 70% fill → LLM-summarise old messages (keep recent N)
- 90% fill → Emergency trim (drop oldest messages)
- Tool schema pruning (only include tools the agent can use)
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── Model Context Window Sizes ──

MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4.1-nano": 1_047_576,
    "o3-mini": 200_000,
    "o3": 200_000,
    "o4-mini": 200_000,
    # Anthropic
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
    "claude-haiku-4": 200_000,
    "claude-3.5-sonnet": 200_000,
    "claude-3.5-haiku": 200_000,
    # Google
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "gemini-1.5-pro": 2_097_152,
    # DeepSeek
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    # Open-source
    "llama-3.3-70b": 128_000,
    "llama-3.1-8b": 128_000,
    "mixtral-8x7b": 32_768,
    "qwen2.5": 32_768,
}

DEFAULT_CONTEXT_WINDOW = 32_000

# ── Thresholds ──

COMPACTION_TRIGGER_PCT = 0.70
EMERGENCY_TRIM_PCT = 0.90
KEEP_RECENT_MESSAGES = 6

# ── Summary prompt ──

COMPACTION_SUMMARY_PROMPT = (
    "Summarise the following student-tutor conversation into structured sections.\n\n"
    "Output exactly this format (keep each section to 1-3 items, total under 200 words):\n\n"
    "## Goals\n- [What the student is trying to achieve]\n\n"
    "## Progress\n- [Key milestones reached, concepts understood]\n\n"
    "## Decisions\n- [Important choices made during the conversation]\n\n"
    "## Next Steps\n- [Planned follow-ups or open questions]\n\n"
    "## Key Facts\n- [Important factual details to remember]\n"
)

INCREMENTAL_COMPACTION_PROMPT = (
    "You have an existing conversation summary and new messages since that summary. "
    "Update the summary by integrating new information into the existing sections. "
    "Do NOT repeat information already captured. Only add genuinely new items or update existing ones.\n\n"
    "Output exactly this format (keep each section to 1-5 items, total under 300 words):\n\n"
    "## Goals\n- [Updated goals]\n\n"
    "## Progress\n- [Updated progress]\n\n"
    "## Decisions\n- [Updated decisions]\n\n"
    "## Next Steps\n- [Updated next steps]\n\n"
    "## Key Facts\n- [Updated key facts]\n"
)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (ASCII ÷4, CJK ÷2)."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return ascii_chars // 4 + non_ascii // 2


def get_context_window(model_name: str) -> int:
    """Look up context window for a model, with fuzzy matching."""
    if not model_name:
        return DEFAULT_CONTEXT_WINDOW

    model_lower = model_name.lower()

    # Exact match first
    if model_lower in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model_lower]

    # Fuzzy: check if any key is contained in the model name
    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if key in model_lower:
            return window

    return DEFAULT_CONTEXT_WINDOW


def estimate_session_tokens(
    messages: list[dict],
    system_prompt: str = "",
    tool_schemas: list[dict] | None = None,
) -> int:
    """Estimate total token usage for a complete LLM call.

    Accounts for: system prompt + conversation messages + tool schemas + framing overhead.
    """
    total = 0

    # System prompt
    total += _estimate_tokens(system_prompt)

    # Messages (role label overhead ≈ 4 tokens per message)
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += _estimate_tokens(content) + 4
        elif isinstance(content, list):
            # Multi-part content (images etc.)
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += _estimate_tokens(part["text"])
            total += 4

    # Tool schemas
    if tool_schemas:
        for schema in tool_schemas:
            # Rough estimate: name + description + parameters JSON
            schema_text = str(schema)
            total += _estimate_tokens(schema_text)

    return total


def emergency_trim(messages: list[dict], budget_tokens: int) -> list[dict]:
    """Hard trim: drop oldest messages until under budget.

    Always keeps the last KEEP_RECENT_MESSAGES messages.
    """
    if len(messages) <= KEEP_RECENT_MESSAGES:
        return messages

    recent = messages[-KEEP_RECENT_MESSAGES:]
    older = messages[:-KEEP_RECENT_MESSAGES]

    # Estimate tokens for recent messages
    recent_tokens = sum(_estimate_tokens(m.get("content", "")) + 4 for m in recent)

    if recent_tokens >= budget_tokens:
        # Even recent messages exceed budget — keep only last 2
        logger.warning("Even recent messages exceed budget; keeping only last 2")
        return messages[-2:]

    remaining_budget = budget_tokens - recent_tokens
    kept = []

    # Keep older messages from most recent backwards until budget exhausted
    for msg in reversed(older):
        msg_tokens = _estimate_tokens(msg.get("content", "")) + 4
        if remaining_budget >= msg_tokens:
            kept.append(msg)
            remaining_budget -= msg_tokens
        else:
            break

    kept.reverse()
    trimmed_count = len(older) - len(kept)
    if trimmed_count > 0:
        logger.info("Emergency trim: dropped %d oldest messages", trimmed_count)

    return kept + recent


async def incremental_compact(
    messages: list[dict],
    existing_summary: str,
    llm_client: Any | None = None,
) -> str | None:
    """Incrementally update an existing structured summary with new messages.

    Returns the updated summary string, or None if LLM call fails.
    """
    if not llm_client or not messages:
        return None

    new_conversation = "\n".join(
        f"{m.get('role', 'unknown')}: {m.get('content', '')}"
        for m in messages
        if m.get("content")
    )

    if not new_conversation.strip():
        return existing_summary

    user_input = (
        f"## Existing Summary\n{existing_summary}\n\n"
        f"## New Messages\n{new_conversation}"
    )

    try:
        updated_summary, _ = await llm_client.extract(
            system_prompt=INCREMENTAL_COMPACTION_PROMPT,
            user_message=user_input,
        )
        logger.info("Incremental compaction: updated summary (%d chars)", len(updated_summary))
        return updated_summary
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        logger.exception("Incremental compaction failed: %s", e)
        return None


MEMORY_FLUSH_PROMPT = (
    "You are extracting important information from a tutoring conversation before it gets compacted.\n\n"
    "Extract ONLY facts that would be valuable to remember long-term:\n"
    "- Student knowledge gaps or misconceptions discovered\n"
    "- Learning preferences observed (visual, step-by-step, examples, etc.)\n"
    "- Topics the student found difficult or easy\n"
    "- Promises or commitments made (exam dates, goals set)\n"
    "- Key insights about the student's understanding level\n\n"
    "Output as a JSON array of objects: [{\"category\": \"knowledge_gap|preference|difficulty|commitment|insight\", "
    "\"content\": \"...\", \"importance\": 0.0-1.0}]\n"
    "If nothing important, output: []"
)


async def memory_flush(
    messages: list[dict],
    llm_client: Any | None = None,
) -> list[dict]:
    """Pre-compaction memory flush — extract important info before summarization.

    Inspired by OpenClaw's memory-flush.ts and Letta's Summarizer pattern.
    Runs BEFORE compact_session() to persist key facts that might be lost
    during summarization.

    Returns a list of extracted memory items (dicts with category, content, importance).
    """
    if not llm_client or not messages:
        return []

    # Only flush messages that are about to be compacted (older ones)
    if len(messages) <= KEEP_RECENT_MESSAGES:
        return []

    older = messages[:-KEEP_RECENT_MESSAGES]
    conversation_text = "\n".join(
        f"{m.get('role', 'unknown')}: {m.get('content', '')}"
        for m in older
        if m.get("content")
    )

    if not conversation_text.strip():
        return []

    try:
        import json
        response, _ = await llm_client.extract(
            system_prompt=MEMORY_FLUSH_PROMPT,
            user_message=conversation_text,
        )

        from libs.text_utils import strip_code_fences
        text = strip_code_fences(response)

        items = json.loads(text)
        if not isinstance(items, list):
            return []

        logger.info("Memory flush: extracted %d items before compaction", len(items))
        return items

    except (ConnectionError, TimeoutError, ValueError, json.JSONDecodeError, RuntimeError) as e:
        logger.exception("Memory flush failed (non-critical): %s", e)
        return []


async def compact_session(
    messages: list[dict],
    model_name: str,
    llm_client: Any | None = None,
) -> tuple[list[dict], list[dict]]:
    """Summarise old messages to reduce token count.

    Strategy:
    0. Run memory_flush() to extract important facts before compaction
    1. Keep last KEEP_RECENT_MESSAGES untouched
    2. LLM-summarise older messages into a single system message
    3. If no LLM available, use emergency_trim as fallback

    Returns:
        (compacted_messages, flushed_memory_items) — the caller is
        responsible for persisting flushed_memory_items (e.g. via
        MemoryPipeline.encode_cells or direct DB insert).
    """
    if len(messages) <= KEEP_RECENT_MESSAGES:
        return messages, []

    # Phase 1: Pre-compaction memory flush (OpenClaw pattern)
    flushed_items = await memory_flush(messages, llm_client)

    recent = messages[-KEEP_RECENT_MESSAGES:]
    older = messages[:-KEEP_RECENT_MESSAGES]

    if not llm_client:
        logger.info("No LLM client for compaction; using emergency trim")
        context_window = get_context_window(model_name)
        return emergency_trim(messages, int(context_window * 0.5)), flushed_items

    # Build text from older messages for summarisation
    conversation_text = "\n".join(
        f"{m.get('role', 'unknown')}: {m.get('content', '')}"
        for m in older
        if m.get("content")
    )

    if not conversation_text.strip():
        return recent, flushed_items

    try:
        summary, _ = await llm_client.extract(
            system_prompt=COMPACTION_SUMMARY_PROMPT,
            user_message=conversation_text,
        )
        logger.info(
            "Session compacted: %d messages → summary (%d chars) + %d recent",
            len(older), len(summary), len(recent),
        )

        # Insert summary as a system message at the beginning
        summary_msg = {
            "role": "system",
            "content": f"[Previous conversation summary]\n{summary}",
            "_structured_summary": True,  # Marker for incremental compaction
        }
        return [summary_msg] + recent, flushed_items

    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as e:
        logger.exception("LLM compaction failed, using emergency trim: %s", e)
        context_window = get_context_window(model_name)
        return emergency_trim(messages, int(context_window * 0.5)), flushed_items


def prune_tool_schemas(
    all_tools: list[dict],
    allowed_tool_names: set[str] | None = None,
) -> list[dict]:
    """Only include tools the current agent is allowed to use.

    Reduces tool schema overhead from all 12 tools to 3-5 per agent,
    saving ~1000-2000 tokens per call.
    """
    if not allowed_tool_names:
        return all_tools  # No filtering

    return [
        tool for tool in all_tools
        if tool.get("function", {}).get("name") in allowed_tool_names
    ]
