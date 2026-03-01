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
import re
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


def build_agent_context(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    conversation_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    history: list[dict] | None = None,
    active_tab: str = "",
    tab_context: dict | None = None,
    scene: str | None = None,
    images: list[dict] | None = None,
) -> AgentContext:
    """Create a normalized AgentContext for chat or workflow entry points."""
    ctx = AgentContext(
        user_id=user_id,
        course_id=course_id,
        user_message=message,
        conversation_id=conversation_id,
        session_id=session_id or uuid.uuid4(),
        conversation_history=(history or [])[-10:],
        active_tab=active_tab,
        tab_context=tab_context or {},
        images=images or [],
    )
    if scene:
        ctx.scene = scene
    return ctx


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


def _has_pending_markers(buffer: str) -> bool:
    return any(marker in buffer for marker in ("[ACTION:", "[TOOL_START:", "[TOOL_DONE:"))


def _parse_action_marker(marker: str) -> dict:
    parts = marker.split(":")
    action_data = {"action": parts[0]}
    if len(parts) >= 2:
        action_data["value"] = parts[1]
    if len(parts) >= 3:
        action_data["extra"] = parts[2]
    return action_data


def _strip_incomplete_markers(buffer: str) -> str:
    return re.sub(r"\[(TOOL_START|TOOL_DONE|ACTION):[^\]]*$", "", buffer)


async def _consume_agent_stream(ctx: AgentContext, agent: BaseAgent, db: AsyncSession) -> AgentContext:
    """Run any agent through its streaming interface and normalize marker output.

    This keeps workflow/non-SSE paths aligned with chat by exercising the same
    tool-capable runtime and stripping UI markers from the persisted response.
    """
    buffer = ""
    content_parts: list[str] = []

    async for chunk in agent.stream(ctx, db):
        buffer += chunk
        changed = True
        while changed:
            changed = False

            if "[TOOL_START:" in buffer:
                start = buffer.index("[TOOL_START:")
                end = buffer.find("]", start)
                if end != -1:
                    before = buffer[:start]
                    if before:
                        content_parts.append(before)
                    buffer = buffer[end + 1:]
                    changed = True
                    continue

            if "[TOOL_DONE:" in buffer:
                start = buffer.index("[TOOL_DONE:")
                end = buffer.find("]", start)
                if end != -1:
                    before = buffer[:start]
                    if before:
                        content_parts.append(before)
                    buffer = buffer[end + 1:]
                    changed = True
                    continue

            if "[ACTION:" in buffer:
                start = buffer.index("[ACTION:")
                end = buffer.find("]", start)
                if end != -1:
                    before = buffer[:start]
                    if before:
                        content_parts.append(before)
                    marker = buffer[start + 8:end]
                    ctx.actions.append(_parse_action_marker(marker))
                    buffer = buffer[end + 1:]
                    changed = True
                    continue

        if buffer and not _has_pending_markers(buffer):
            content_parts.append(buffer)
            buffer = ""
        elif _has_pending_markers(buffer) and len(buffer) > 500:
            logger.warning("Flushing oversized marker buffer (%d chars)", len(buffer))
            content_parts.append(buffer)
            buffer = ""

    if buffer:
        cleaned = _strip_incomplete_markers(buffer)
        if cleaned:
            content_parts.append(cleaned)

    cleaned_response = "".join(content_parts).strip()
    if cleaned_response:
        ctx.response = cleaned_response
    return ctx


def _finalize_token_usage(ctx: AgentContext, agent: BaseAgent) -> None:
    """Normalize token accounting for direct-stream and ReAct paths."""
    try:
        client = agent.get_llm_client()
        should_add_last_usage = (
            ctx.react_iterations == 0
            or not hasattr(client, "chat_with_tools")
        )
        usage = client.get_last_usage()
        if usage and should_add_last_usage:
            ctx.input_tokens += usage.get("input_tokens", 0)
            ctx.output_tokens += usage.get("output_tokens", 0)
        ctx.total_tokens = ctx.input_tokens + ctx.output_tokens
    except Exception as e:
        logger.debug("Token tracking unavailable: %s", e)


def _build_provenance(ctx: AgentContext) -> dict:
    """Create a compact provenance summary for UI and persistence."""
    return {
        "scene": ctx.scene,
        "scene_resolution": ctx.metadata.get("scene_resolution"),
        "scene_switch": ctx.metadata.get("scene_switch"),
        "preferences_applied": sorted(ctx.preferences.keys()),
        "preference_sources": ctx.preference_sources,
        "preference_details": [
            {
                "dimension": key,
                "value": value,
                "source": ctx.preference_sources.get(key, "unknown"),
            }
            for key, value in sorted(ctx.preferences.items())
        ],
        "content_count": len(ctx.content_docs),
        "content_titles": [doc.get("title", "") for doc in ctx.content_docs[:3] if doc.get("title")],
        "content_refs": [
            {
                "title": doc.get("title"),
                "source_type": doc.get("source_type"),
                "preview": (doc.get("content") or "")[:140],
            }
            for doc in ctx.content_docs[:3]
            if doc.get("title") or doc.get("content")
        ],
        "memory_count": len(ctx.memories),
        "tool_count": len(ctx.tool_calls),
        "tool_names": [call.get("tool") for call in ctx.tool_calls[:5] if call.get("tool")],
        "action_count": len(ctx.actions),
    }


# ── Context Loading ──

async def load_context(ctx: AgentContext, db: AsyncSession) -> AgentContext:
    """Load preferences, memories, and RAG content.

    These run sequentially because AsyncSession does not permit overlapping DB
    work on the same connection.  Each step is wrapped in its own try/except so
    a failure in one does not block the others.
    """
    ctx.transition(TaskPhase.LOADING_CONTEXT)

    from services.preference.engine import resolve_preferences
    from services.preference.scene import explain_scene_detection
    from services.memory.pipeline import retrieve_memories

    # Detect scene for preference cascade (only if not explicitly set by caller)
    if ctx.scene == "study_session":
        scene_resolution = explain_scene_detection(ctx.user_message)
        ctx.scene = scene_resolution["scene"]
        ctx.metadata["scene_resolution"] = scene_resolution
    else:
        ctx.metadata["scene_resolution"] = {
            "scene": ctx.scene,
            "mode": "explicit",
            "matched_text": None,
            "reason": "Scene provided by the caller or course context.",
        }

    # Use rag-fusion for complex queries, regular hybrid for simple ones
    async def search_content():
        # Use rag-fusion for LEARN/REVIEW intents (benefit from multi-query)
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

    # Apply context window budget trimming (OpenClaw compaction)
    ctx = _trim_context(ctx)

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


async def prepare_agent_turn(ctx: AgentContext, db: AsyncSession) -> tuple[AgentContext, BaseAgent]:
    """Run shared orchestration steps before agent execution."""
    ctx.transition(TaskPhase.ROUTING)
    ctx = await classify_intent(ctx)
    ctx = await load_context(ctx, db)

    fatigue = _detect_fatigue(ctx.user_message)
    if fatigue > 0.6 and "motivation" in AGENT_REGISTRY:
        agent = AGENT_REGISTRY["motivation"]
        ctx.metadata["fatigue_level"] = fatigue
    else:
        agent = get_agent(ctx.intent)
    ctx.delegated_agent = agent.name
    return ctx, agent


async def apply_reflection(ctx: AgentContext) -> AgentContext:
    """Optionally improve long substantive responses."""
    if not ctx.response or ctx.intent not in (IntentType.LEARN, IntentType.REVIEW) or len(ctx.response) <= 100:
        return ctx
    try:
        original_response = ctx.response
        ctx.transition(TaskPhase.VERIFYING)
        from services.agent.reflection import reflect_and_improve

        ctx = await reflect_and_improve(ctx)
        ctx.metadata["response_replaced"] = (
            ctx.response != original_response
            and ctx.metadata.get("reflection", {}).get("improved")
        )
    except Exception as e:
        logger.warning("Reflection failed (non-critical): %s", e)
    return ctx


async def run_agent_turn(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    db: AsyncSession,
    db_factory,
    conversation_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    history: list[dict] | None = None,
    active_tab: str = "",
    tab_context: dict | None = None,
    scene: str | None = None,
    post_process_inline: bool = False,
) -> AgentContext:
    """One-shot orchestration path reused by workflows and non-streaming entry points."""
    ctx = build_agent_context(
        user_id=user_id,
        course_id=course_id,
        message=message,
        conversation_id=conversation_id,
        session_id=session_id,
        history=history,
        active_tab=active_tab,
        tab_context=tab_context,
        scene=scene,
    )
    ctx, agent = await prepare_agent_turn(ctx, db)
    ctx = await _consume_agent_stream(ctx, agent, db)
    _finalize_token_usage(ctx, agent)
    ctx = await apply_reflection(ctx)
    if ctx.response and post_process_inline:
        await post_process(ctx, db_factory)
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

            # 4. Auto-consolidation (every N messages)
            async def auto_consolidate():
                from services.agent.memory_agent import maybe_auto_consolidate
                await maybe_auto_consolidate(db, ctx.user_id, ctx.course_id)

            # Execute sequentially — AsyncSession is NOT safe for concurrent use.
            # _retry_async handles per-task error isolation (returns None on failure).
            for coro_fn, name, retries in [
                (extract_signal, "signal_extraction", 2),
                (encode_mem, "memory_encoding", 2),
                (extract_graph, "graph_extraction", 1),
                (auto_consolidate, "auto_consolidation", 1),
            ]:
                await _retry_async(coro_fn, name, max_retries=retries)

            # Commit whatever succeeded — partial results are better than none
            await db.commit()

    except Exception as e:
        logger.warning("Post-processing failed: %s", e, exc_info=True)

    ctx.mark_completed()


async def wait_for_background_tasks(timeout: float = 5.0) -> None:
    """Wait for in-flight background tasks during graceful shutdown."""
    if not _background_tasks:
        return
    pending = list(_background_tasks)
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for %d background task(s) during shutdown", len(pending))


# ── Fatigue Detection (OpenAkita Persona pattern) ──

def _detect_fatigue(message: str) -> float:
    """Detect student frustration/fatigue level (0.0-1.0).

    OpenAkita persona dimension pattern: check signals across multiple categories.
    Positive signals reduce the score to prevent false positives.
    """
    FATIGUE_SIGNALS = [
        (r"(不想学|不会了|太难了|放弃|好烦|好累|学不动)", 0.35),
        (r"(confused|tired|give up|too hard|frustrated|hate this|can't do)", 0.35),
        (r"(看不懂|学不会|怎么还是错|又错了|做不出来)", 0.3),
        (r"(again wrong|still don't get|keep getting wrong|makes no sense)", 0.3),
        (r"(算了吧|哎|唉|sigh|ugh|whatever|nvm|forget it)", 0.25),
        (r"[😫😤😩😭💀🤯😡]{1}", 0.2),
    ]
    POSITIVE_SIGNALS = [
        (r"(我懂了|明白了|原来如此|学会了|掌握了|搞定了)", -0.3),
        (r"(i see|got it|makes sense|understand now|figured it out)", -0.3),
        (r"(谢谢|不错|挺好|thank|great|nice|cool)", -0.15),
    ]
    score = 0.0
    for pattern, weight in FATIGUE_SIGNALS:
        if re.search(pattern, message, re.IGNORECASE):
            score += weight
    for pattern, weight in POSITIVE_SIGNALS:
        if re.search(pattern, message, re.IGNORECASE):
            score += weight
    return max(0.0, min(score, 1.0))


# ── Main Orchestration ──

async def orchestrate_stream(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    db: AsyncSession,
    db_factory,
    conversation_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    history: list[dict] | None = None,
    active_tab: str = "",
    tab_context: dict | None = None,
    scene: str | None = None,
    images: list[dict] | None = None,
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
    ctx = build_agent_context(
        user_id=user_id,
        course_id=course_id,
        message=message,
        conversation_id=conversation_id,
        session_id=session_id,
        history=history,
        active_tab=active_tab,
        tab_context=tab_context,
        scene=scene,
        images=images,
    )

    # Emit agent status
    yield {"event": "status", "data": json.dumps({"phase": "routing"})}

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

    # 3. Load context (sequential — AsyncSession constraint)
    ctx = await load_context(ctx, db)

    # Detect complex multi-step requests and submit as background task
    from services.agent.task_planner import is_complex_request
    if is_complex_request(ctx.user_message) and ctx.intent in (IntentType.PLAN, IntentType.LEARN, IntentType.REVIEW):
        try:
            from services.agent.task_planner import create_plan
            from services.activity.engine import submit_task

            plan_steps = await create_plan(ctx.user_message, ctx.user_id, ctx.course_id)
            task = await submit_task(
                user_id=ctx.user_id,
                task_type="multi_step",
                title=f"Multi-step plan: {ctx.user_message[:100]}",
                course_id=ctx.course_id,
                source="chat",
                input_json={"steps": plan_steps, "course_id": str(ctx.course_id)},
            )
            yield {
                "event": "plan_step",
                "data": json.dumps({
                    "task_id": str(task.id),
                    "steps": [{"title": s["title"], "status": "pending"} for s in plan_steps],
                    "message": "I've created a multi-step plan for your request. It's running in the background.",
                }),
            }
            ctx.metadata["multi_step_task_id"] = str(task.id)
        except Exception as e:
            logger.warning("Multi-step planning failed, falling back to single turn: %s", e)

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

    # 5. Stream response with marker parsing + token tracking
    # Markers: [ACTION:...] (UI actions), [TOOL_START:...] / [TOOL_DONE:...] (ReAct tools)
    buffer = ""
    async for chunk in agent.stream(ctx, db):
        buffer += chunk

        # Parse markers one at a time until no more complete markers found
        changed = True
        while changed:
            changed = False

            # Parse [TOOL_START:tool_name] markers
            if "[TOOL_START:" in buffer:
                start = buffer.index("[TOOL_START:")
                end = buffer.find("]", start)
                if end != -1:
                    before = buffer[:start]
                    if before:
                        yield {"event": "message", "data": json.dumps({"content": before})}
                    tool_name = buffer[start + 12:end]
                    yield {
                        "event": "tool_status",
                        "data": json.dumps({"status": "running", "tool": tool_name}),
                    }
                    buffer = buffer[end + 1:]
                    changed = True
                    continue

            # Parse [TOOL_DONE:tool_name] markers
            if "[TOOL_DONE:" in buffer:
                start = buffer.index("[TOOL_DONE:")
                end = buffer.find("]", start)
                if end != -1:
                    before = buffer[:start]
                    if before:
                        yield {"event": "message", "data": json.dumps({"content": before})}
                    tool_name = buffer[start + 11:end]
                    yield {
                        "event": "tool_status",
                        "data": json.dumps({"status": "complete", "tool": tool_name}),
                    }
                    buffer = buffer[end + 1:]
                    changed = True
                    continue

            # Parse [ACTION:...] markers (existing UI action system)
            if "[ACTION:" in buffer:
                start = buffer.index("[ACTION:")
                end = buffer.find("]", start)
                if end != -1:
                    before = buffer[:start]
                    if before:
                        yield {"event": "message", "data": json.dumps({"content": before})}
                    marker = buffer[start + 8:end]
                    action_data = _parse_action_marker(marker)
                    ctx.actions.append(action_data)
                    yield {"event": "action", "data": json.dumps(action_data)}
                    buffer = buffer[end + 1:]
                    changed = True
                    continue

        # Yield remaining buffer content (no pending markers)
        has_pending = any(m in buffer for m in ("[ACTION:", "[TOOL_START:", "[TOOL_DONE:"))
        if buffer and not has_pending:
            yield {"event": "message", "data": json.dumps({"content": buffer})}
            buffer = ""
        elif has_pending and len(buffer) > 500:
            # Safety: if buffer grows too large with an incomplete marker,
            # the marker is likely malformed — flush everything as text
            logger.warning("Flushing oversized marker buffer (%d chars)", len(buffer))
            yield {"event": "message", "data": json.dumps({"content": buffer})}
            buffer = ""

    # Yield any remaining buffer (strip incomplete markers)
    if buffer:
        # Remove stray incomplete markers that never closed
        buffer = re.sub(r"\[(TOOL_START|TOOL_DONE|ACTION):[^\]]*$", "", buffer)
        if buffer:
            yield {"event": "message", "data": json.dumps({"content": buffer})}

    _finalize_token_usage(ctx, agent)

    should_reflect = (
        bool(ctx.response)
        and ctx.intent in (IntentType.LEARN, IntentType.REVIEW)
        and len(ctx.response) > 100
    )
    if should_reflect:
        yield {"event": "status", "data": json.dumps({"phase": "verifying"})}
        ctx = await apply_reflection(ctx)
    if ctx.metadata.get("response_replaced"):
        yield {"event": "replace", "data": json.dumps({"content": ctx.response})}

    # Done streaming
    yield {
        "event": "done",
        "data": json.dumps({
            "status": "complete",
            "agent": agent.name,
            "intent": ctx.intent.value,
            "session_id": str(ctx.session_id),
            "tokens": ctx.total_tokens,
            "actions": ctx.actions,
            "provenance": _build_provenance(ctx),
            "reflection": ctx.metadata.get("reflection"),
        }),
    }

    # 7. Post-processing with retry (tracked to prevent GC and enable graceful shutdown)
    if ctx.response:
        task = asyncio.create_task(post_process(ctx, db_factory))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
