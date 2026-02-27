"""Orchestrator — central coordinator for multi-agent architecture.

Borrows from:
- HelloAgents ProgrammingTutor: TutorAgent → PlannerAgent / ExerciseAgent routing
- MetaGPT Team: role-based dispatch + shared memory
- OpenClaw: agent.list + bindings + queue lanes + Memory Flush
- OpenAkita: state machine lifecycle
- NanoClaw group-queue: exponential backoff retry for post-processing

Flow:
1. Classify intent (rule match → LLM fallback)
2. Load context (preferences, memories, RAG via rag-fusion in parallel)
3. Trim context to token budget (OpenClaw compaction pattern)
4. Route to specialist agent (with model_preference support)
5. Stream response + collect token usage
6. Reflection self-check (optional VERIFYING phase)
7. Post-process with retry (signal extraction, memory encoding, graph extraction)
"""

import asyncio
import json
import logging
import uuid
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, IntentType, TaskPhase
from services.agent.router import classify_intent
from services.agent.base import BaseAgent
from services.agent.teaching import TeachingAgent
from services.agent.exercise import ExerciseAgent
from services.agent.planning import PlanningAgent
from services.agent.review import ReviewAgent
from services.agent.preference_agent import PreferenceAgent
from services.agent.scene_agent import SceneAgent
from services.agent.code_execution import CodeExecutionAgent
from services.agent.curriculum import CurriculumAgent
from services.agent.assessment import AssessmentAgent
from services.agent.motivation import MotivationAgent

logger = logging.getLogger(__name__)

# ── Background Task Tracking ──
# Keep weak references to post-processing tasks so they don't get GC'd
# and we can await them during graceful shutdown.
_background_tasks: set[asyncio.Task] = set()


# ── Agent Registry ──

AGENT_REGISTRY: dict[str, BaseAgent] = {
    "teaching": TeachingAgent(),
    "exercise": ExerciseAgent(),
    "planning": PlanningAgent(),
    "review": ReviewAgent(),
    "preference": PreferenceAgent(),
    "scene": SceneAgent(),
    "code_execution": CodeExecutionAgent(),
    "curriculum": CurriculumAgent(),
    "assessment": AssessmentAgent(),
    "motivation": MotivationAgent(),
}

# Intent → Agent mapping (OpenClaw binding pattern, v3: + scene_switch + new agents)
INTENT_AGENT_MAP: dict[IntentType, str] = {
    IntentType.LEARN: "teaching",
    IntentType.QUIZ: "exercise",
    IntentType.PLAN: "planning",
    IntentType.REVIEW: "review",
    IntentType.PREFERENCE: "preference",
    IntentType.LAYOUT: "preference",       # Layout changes go through preference agent
    IntentType.GENERAL: "teaching",        # General chat defaults to teaching
    IntentType.SCENE_SWITCH: "scene",      # v3: Scene transition suggestions
    IntentType.CODE: "code_execution",     # Code execution requests
    IntentType.CURRICULUM: "curriculum",   # Course structure analysis
    IntentType.ASSESS: "assessment",       # Learning assessment & reports
}


def get_agent(intent: IntentType) -> BaseAgent:
    """Resolve intent to specialist agent (OpenClaw binding resolution)."""
    agent_name = INTENT_AGENT_MAP.get(intent, "teaching")
    return AGENT_REGISTRY[agent_name]


# ── Context Window Management (OpenClaw compaction pattern) ──

# Token budgets for each context category
MEMORY_BUDGET = 1500
RAG_BUDGET = 3000
HISTORY_BUDGET = 2000


def _estimate_tokens(text: str) -> int:
    """Rough token estimate (English ÷4, CJK ÷2)."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    non_ascii = len(text) - ascii_chars
    return ascii_chars // 4 + non_ascii // 2


def _trim_context(ctx: AgentContext) -> AgentContext:
    """Trim context to fit token budgets. Keeps highest-relevance items.

    OpenClaw compaction pattern: soft trim by priority, preserving most useful content.
    """
    # 1. Trim conversation history (keep newest, drop oldest)
    history_tokens = sum(_estimate_tokens(m.get("content", "")) for m in ctx.conversation_history)
    while history_tokens > HISTORY_BUDGET and len(ctx.conversation_history) > 2:
        removed = ctx.conversation_history.pop(0)
        history_tokens -= _estimate_tokens(removed.get("content", ""))

    # 2. Trim RAG docs (sorted by relevance; drop lowest-scored last items)
    rag_tokens = sum(_estimate_tokens(d.get("content", "")) for d in ctx.content_docs)
    while rag_tokens > RAG_BUDGET and ctx.content_docs:
        removed = ctx.content_docs.pop()
        rag_tokens -= _estimate_tokens(removed.get("content", ""))

    # 3. Trim memories (sorted by hybrid_score; drop lowest last items)
    mem_tokens = sum(_estimate_tokens(m.get("summary", "")) for m in ctx.memories)
    while mem_tokens > MEMORY_BUDGET and ctx.memories:
        removed = ctx.memories.pop()
        mem_tokens -= _estimate_tokens(removed.get("summary", ""))

    return ctx


# ── Context Loading ──

async def load_context(ctx: AgentContext, db: AsyncSession) -> AgentContext:
    """Load preferences, memories, and RAG content in parallel.

    Uses rag-fusion for enhanced multi-query retrieval when available.
    Runs three async tasks concurrently for minimal latency.
    Applies _trim_context() to fit within token budgets.
    """
    ctx.transition(TaskPhase.LOADING_CONTEXT)

    from services.preference.engine import resolve_preferences
    from services.preference.scene import detect_scene
    from services.memory.pipeline import retrieve_memories

    # Detect scene for preference cascade
    ctx.scene = detect_scene(ctx.user_message)

    # Use rag-fusion for complex queries, regular hybrid for simple ones
    async def search_content():
        # Use rag-fusion for LEARN/REVIEW intents (benefit from multi-query)
        if ctx.intent in (IntentType.LEARN, IntentType.REVIEW):
            from services.search.rag_fusion import rag_fusion_search
            return await rag_fusion_search(db, ctx.course_id, ctx.user_message, limit=5)
        else:
            from services.search.hybrid import hybrid_search
            return await hybrid_search(db, ctx.course_id, ctx.user_message, limit=5)

    # Parallel context loading
    pref_task = resolve_preferences(db, ctx.user_id, ctx.course_id, scene=ctx.scene)
    memory_task = retrieve_memories(db, ctx.user_id, ctx.user_message, ctx.course_id, limit=3)
    rag_task = search_content()

    resolved, memories, content_docs = await asyncio.gather(
        pref_task, memory_task, rag_task, return_exceptions=True,
    )

    # Handle individual failures gracefully
    if not isinstance(resolved, Exception):
        ctx.preferences = resolved.preferences
        ctx.preference_sources = resolved.sources
    else:
        logger.warning("Preference loading failed: %s", resolved)

    if not isinstance(memories, Exception):
        ctx.memories = memories
    else:
        logger.warning("Memory retrieval failed: %s", memories)

    if not isinstance(content_docs, Exception):
        ctx.content_docs = content_docs
    else:
        logger.warning("RAG search failed: %s", content_docs)

    # Apply context window budget trimming (OpenClaw compaction)
    ctx = _trim_context(ctx)

    return ctx


# ── Post-Processing with Retry (NanoClaw group-queue pattern) ──

async def _retry_async(coro_fn, name: str, max_retries: int = 2, base_delay: float = 1.0):
    """Execute an async coroutine with exponential backoff retry.

    Borrowed from NanoClaw group-queue.ts: 5s→10s→20s backoff pattern,
    adapted with shorter delays for post-processing tasks (1s→2s→4s).
    """
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn()
        except Exception as e:
            if attempt == max_retries:
                logger.warning("Post-process '%s' failed after %d retries: %s", name, max_retries, e)
                return None
            delay = base_delay * (2 ** attempt)
            logger.debug("Retrying '%s' in %.1fs (attempt %d/%d): %s", name, delay, attempt + 1, max_retries, e)
            await asyncio.sleep(delay)


async def post_process(ctx: AgentContext, db_factory) -> None:
    """Async post-processing: signal extraction + memory encoding + graph extraction.

    OpenAkita Compiler pattern: lightweight async tasks after main response.
    NanoClaw retry pattern: exponential backoff on failure.
    Uses a new DB session to avoid session lifecycle issues.
    """
    ctx.transition(TaskPhase.POST_PROCESSING)
    try:
        async with db_factory() as db:
            # 1. Preference signal extraction (~95% return NONE)
            async def extract_signal():
                from services.preference.extractor import extract_preference_signal
                from services.preference.confidence import process_signal_to_preference
                from models.preference import PreferenceSignal

                signal = await extract_preference_signal(
                    ctx.user_message, ctx.response, ctx.user_id, ctx.course_id,
                )
                if not signal:
                    return
                ctx.extracted_signal = signal
                ps = PreferenceSignal(
                    user_id=signal["user_id"],
                    course_id=signal.get("course_id"),
                    signal_type=signal["signal_type"],
                    dimension=signal["dimension"],
                    value=signal["value"],
                    context=signal.get("context"),
                )
                db.add(ps)
                await db.flush()
                await process_signal_to_preference(
                    db, signal["user_id"], signal["dimension"], signal.get("course_id"),
                )
                logger.info("Signal extracted: dim=%s val=%s", signal["dimension"], signal["value"])

            # 2. Memory encoding (EverMemOS Stage 1 — MemCell atomic extraction)
            async def encode_mem():
                from services.memory.pipeline import encode_memory
                await encode_memory(db, ctx.user_id, ctx.course_id, ctx.user_message, ctx.response)

            # 3. Graph memory extraction (mem0 pattern — entity/relationship extraction)
            async def extract_graph():
                from services.knowledge.graph_memory import extract_graph_entities, store_graph_entities
                extracted = await extract_graph_entities(
                    ctx.user_message, ctx.response,
                )
                if extracted.get("entities") or extracted.get("relationships"):
                    await store_graph_entities(db, ctx.user_id, ctx.course_id, extracted)

            # Execute with retry (NanoClaw exponential backoff)
            await asyncio.gather(
                _retry_async(extract_signal, "signal_extraction", max_retries=2),
                _retry_async(encode_mem, "memory_encoding", max_retries=2),
                _retry_async(extract_graph, "graph_extraction", max_retries=1),
                return_exceptions=True,
            )
            await db.commit()

    except Exception as e:
        logger.warning("Post-processing failed: %s", e, exc_info=True)

    ctx.mark_completed()


# ── Fatigue Detection (OpenAkita Persona pattern) ──

def _detect_fatigue(message: str) -> float:
    """Detect student frustration/fatigue level (0.0-1.0).

    OpenAkita persona dimension pattern: check signals across multiple categories.
    """
    import re
    FATIGUE_SIGNALS = [
        r"(不想学|不会|太难|放弃|烦|累|confused|tired|give up|too hard|frustrated)",
        r"(看不懂|学不会|怎么还是错|again wrong|still don't get)",
        r"^(算了|哎|唉|sigh|ugh|whatever)$",
    ]
    score = 0.0
    for pattern in FATIGUE_SIGNALS:
        if re.search(pattern, message, re.IGNORECASE):
            score += 0.3
    return min(score, 1.0)


# ── Main Orchestration ──

async def orchestrate_stream(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    db: AsyncSession,
    db_factory,
    conversation_id: uuid.UUID | None = None,
    history: list[dict] | None = None,
    active_tab: str = "",
    tab_context: dict | None = None,
    scene: str | None = None,
) -> AsyncIterator[dict]:
    """Main orchestration entry point for streaming responses.

    Yields SSE-compatible event dicts: {"event": str, "data": str}

    Flow:
    1. Create AgentContext (with conversation history from frontend)
    2. Classify intent
    3. Check fatigue (OpenAkita persona intercept)
    4. Load context (parallel) + trim to budget
    5. Route to specialist agent
    6. Stream response with [ACTION:...] marker parsing + token tracking
    7. Reflection self-check (optional VERIFYING phase)
    8. Fire-and-forget post-processing with retry
    """
    # 1. Initialize context with conversation history
    ctx = AgentContext(
        user_id=user_id,
        course_id=course_id,
        user_message=message,
        conversation_id=conversation_id,
        conversation_history=(history or [])[-10:],  # Keep last 10 turns
        active_tab=active_tab,
        tab_context=tab_context or {},
    )
    # Use frontend-provided scene if available (from course.active_scene)
    if scene:
        ctx.scene = scene

    # Emit agent status
    yield {"event": "status", "data": json.dumps({"phase": "routing"})}

    # 2. Classify intent
    ctx.transition(TaskPhase.ROUTING)
    ctx = await classify_intent(ctx)

    yield {
        "event": "status",
        "data": json.dumps({
            "phase": "loading",
            "intent": ctx.intent.value,
            "confidence": ctx.intent_confidence,
        }),
    }

    # 3. Load context in parallel
    ctx = await load_context(ctx, db)

    # 4. Route to specialist agent (with fatigue intercept)
    fatigue = _detect_fatigue(ctx.user_message)
    if fatigue > 0.6 and "motivation" in AGENT_REGISTRY:
        agent = AGENT_REGISTRY["motivation"]
        ctx.metadata["fatigue_level"] = fatigue
    else:
        agent = get_agent(ctx.intent)
    ctx.delegated_agent = agent.name

    yield {
        "event": "status",
        "data": json.dumps({
            "phase": "generating",
            "agent": agent.name,
        }),
    }

    # 5. Stream response with action marker parsing + token tracking
    buffer = ""
    async for chunk in agent.stream(ctx, db):
        buffer += chunk

        # Parse [ACTION:...] markers from buffer
        while "[ACTION:" in buffer:
            start = buffer.index("[ACTION:")
            end = buffer.find("]", start)
            if end == -1:
                break  # Incomplete marker, wait for more data

            # Yield text before the marker
            before = buffer[:start]
            if before:
                yield {"event": "message", "data": json.dumps({"content": before})}

            # Parse and yield the action
            marker = buffer[start + 8:end]
            parts = marker.split(":")
            action_data = {"action": parts[0]}
            if len(parts) >= 2:
                action_data["value"] = parts[1]
            if len(parts) >= 3:
                action_data["extra"] = parts[2]
            yield {"event": "action", "data": json.dumps(action_data)}

            buffer = buffer[end + 1:]

        # Yield remaining buffer content (no pending markers)
        if buffer and "[ACTION:" not in buffer:
            yield {"event": "message", "data": json.dumps({"content": buffer})}
            buffer = ""

    # Yield any remaining buffer
    if buffer:
        yield {"event": "message", "data": json.dumps({"content": buffer})}

    # Token tracking: get usage from the LLM client after streaming (OpenClaw SessionEntry)
    try:
        client = agent.get_llm_client()
        usage = client.get_last_usage()
        if usage:
            ctx.input_tokens = usage.get("input_tokens", 0)
            ctx.output_tokens = usage.get("output_tokens", 0)
            ctx.total_tokens = ctx.input_tokens + ctx.output_tokens
    except Exception:
        pass  # Token tracking is best-effort

    # 6. Reflection self-check (VERIFYING phase, OpenAkita pattern)
    # Only for substantive responses from teaching/review agents
    if ctx.response and ctx.intent in (IntentType.LEARN, IntentType.REVIEW) and len(ctx.response) > 100:
        ctx.transition(TaskPhase.VERIFYING)
        yield {"event": "status", "data": json.dumps({"phase": "verifying"})}
        try:
            from services.agent.reflection import reflect_and_improve
            original_response = ctx.response
            ctx = await reflect_and_improve(ctx)
            # If reflection improved the response, send a replacement
            if ctx.response != original_response and ctx.metadata.get("reflection", {}).get("improved"):
                yield {
                    "event": "replace",
                    "data": json.dumps({"content": ctx.response}),
                }
        except Exception as e:
            logger.warning("Reflection failed (non-critical): %s", e)

    # Done streaming
    yield {
        "event": "done",
        "data": json.dumps({
            "status": "complete",
            "agent": agent.name,
            "intent": ctx.intent.value,
            "session_id": str(ctx.session_id),
            "tokens": ctx.total_tokens,
            "reflection": ctx.metadata.get("reflection"),
        }),
    }

    # 7. Post-processing with retry (tracked to prevent GC and enable graceful shutdown)
    if ctx.response:
        task = asyncio.create_task(post_process(ctx, db_factory))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
