"""Orchestrator — central coordinator for multi-agent architecture.

Flow:
1. Classify intent (rule match → LLM fallback)
2. Load context (preferences, memories, RAG via rag-fusion in parallel)
3. Trim context to token budget (OpenClaw compaction pattern)
4. Route to specialist agent (with model_preference support)
5. Stream response + collect token usage
6. Reflection self-check (optional VERIFYING phase)
7. Post-process with retry (signal extraction, memory encoding, graph extraction)

Registry and context loading extracted to:
- services.agent.registry — agent registration + intent mapping
- services.agent.context_builder — context loading + token trimming
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import asdict
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, AgentTurnEnvelope, AgentVerificationResult, IntentType, TaskPhase
from services.agent.router import classify_intent
from services.agent.base import BaseAgent
from services.agent.registry import AGENT_REGISTRY, get_agent, build_agent_context
from services.agent.context_builder import load_context
from services.agent.swarm import should_use_swarm
from services.agent.merger import merge_results

logger = logging.getLogger(__name__)

# ── Background Task Tracking ──
# Tracked set for fire-and-forget tasks; safe under asyncio's cooperative
# single-threaded model (no preemptive context switches within set ops).
_background_tasks: set[asyncio.Task] = set()




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
    from services.provenance import build_provenance

    payload = build_provenance(
        scene=ctx.scene,
        content_refs=[
            {
                "title": doc.get("title"),
                "source_type": doc.get("source_type"),
                "preview": (doc.get("content") or "")[:140],
            }
            for doc in ctx.content_docs[:3]
            if doc.get("title") or doc.get("content")
        ],
        content_count=len(ctx.content_docs),
        memory_count=len(ctx.memories),
        tool_names=[call.get("tool") for call in ctx.tool_calls[:5] if call.get("tool")],
        action_count=len(ctx.actions),
        generated=True,
        user_input=bool((ctx.user_message or "").strip()),
        source_labels=["generated"],
    )
    payload.update({
        "course_count": len(ctx.content_docs),
        "scene_resolution": ctx.metadata.get("scene_resolution"),
        "scene_policy": ctx.metadata.get("scene_policy"),
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
        "workflow_count": 1 if ctx.metadata.get("workflow_name") else 0,
        "generated_count": 1 if ctx.response else 0,
    })
    return payload


def _get_verifier_result(ctx: AgentContext) -> AgentVerificationResult | None:
    verifier_payload = ctx.metadata.get("verifier")
    if not isinstance(verifier_payload, dict):
        return None
    try:
        return AgentVerificationResult(
            status=verifier_payload["status"],
            code=verifier_payload["code"],
            message=verifier_payload["message"],
            repair_attempted=bool(verifier_payload.get("repair_attempted", False)),
        )
    except KeyError:
        return None


def _build_turn_envelope(ctx: AgentContext) -> AgentTurnEnvelope:
    return AgentTurnEnvelope(
        response=ctx.response,
        agent=ctx.delegated_agent or "coordinator",
        intent=ctx.intent.value,
        actions=ctx.actions,
        tool_calls=ctx.tool_calls,
        provenance=ctx.metadata.get("provenance") or _build_provenance(ctx),
        verifier=_get_verifier_result(ctx),
        task_link=ctx.metadata.get("task_link"),
    )


def _envelope_payload(ctx: AgentContext) -> dict:
    envelope = _build_turn_envelope(ctx)
    return {
        "status": "complete",
        "session_id": str(ctx.session_id),
        "response": envelope.response,
        "agent": envelope.agent,
        "intent": envelope.intent,
        "tokens": ctx.total_tokens,
        "actions": envelope.actions,
        "tool_calls": envelope.tool_calls,
        "provenance": envelope.provenance,
        "verifier": asdict(envelope.verifier) if envelope.verifier else None,
        "task_link": envelope.task_link,
        "reflection": ctx.metadata.get("reflection"),
    }


async def apply_verifier(ctx: AgentContext, agent: BaseAgent) -> AgentContext:
    if ctx.intent not in (IntentType.LEARN, IntentType.REVIEW, IntentType.QUIZ, IntentType.PLAN, IntentType.ASSESS):
        return ctx
    try:
        from services.agent.verifier import verify_and_repair

        original_response = ctx.response
        ctx.transition(TaskPhase.VERIFYING)
        ctx.metadata["provenance"] = _build_provenance(ctx)
        ctx = await verify_and_repair(ctx, agent)
        ctx.metadata["verifier_replaced"] = ctx.response != original_response
    except Exception as e:
        logger.warning("Verifier failed (non-critical): %s", e)
    return ctx


# load_context imported from services.agent.context_builder

async def prepare_agent_turn(
    ctx: AgentContext, db: AsyncSession, db_factory=None,
) -> tuple[AgentContext, BaseAgent]:
    """Run shared orchestration steps before agent execution."""
    ctx.transition(TaskPhase.ROUTING)
    ctx = await classify_intent(ctx)
    ctx = await load_context(ctx, db, db_factory=db_factory)

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
    verifier_status = (ctx.metadata.get("verifier") or {}).get("status")
    if verifier_status == "failed":
        return ctx
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
    ctx, agent = await prepare_agent_turn(ctx, db, db_factory=db_factory)
    ctx = await _consume_agent_stream(ctx, agent, db)
    _finalize_token_usage(ctx, agent)
    ctx.metadata["provenance"] = _build_provenance(ctx)
    ctx = await apply_verifier(ctx, agent)
    ctx = await apply_reflection(ctx)
    ctx.metadata["provenance"] = _build_provenance(ctx)
    ctx.metadata["turn_envelope"] = _envelope_payload(ctx)
    if ctx.response and post_process_inline:
        await post_process(ctx, db_factory)
    return ctx


async def orchestrate_simple(
    user_id,
    message: str,
    channel: str = "api",
    db=None,
    course_id=None,
) -> str:
    """Non-streaming orchestration for webhook/channel integrations.

    Lightweight wrapper around ``run_agent_turn`` that returns just the text
    response.  If no course_id is provided, attempts to find the user's most
    recent course.  If no database session is provided, creates one.

    Args:
        user_id: The user's UUID.
        message: The user's message text.
        channel: Channel identifier (e.g. "telegram", "discord").
        db: Optional active database session.
        course_id: Optional course UUID. If None, resolves from user's courses.

    Returns:
        The agent's text response, or an error message string.
    """
    from database import async_session

    try:
        async with async_session() as session:
            # Resolve course_id if not provided
            if course_id is None:
                from sqlalchemy import select
                from models.course import Course

                stmt = (
                    select(Course.id)
                    .where(Course.user_id == user_id)
                    .order_by(Course.updated_at.desc())
                    .limit(1)
                )
                result = await session.execute(stmt)
                course_id = result.scalar_one_or_none()

                if course_id is None:
                    return "You don't have any courses yet. Create one on the web app first."

            ctx = await run_agent_turn(
                user_id=user_id,
                course_id=course_id,
                message=message,
                db=session,
                db_factory=async_session,
                post_process_inline=True,
            )

            return ctx.response or "I couldn't process that. Please try again."

    except Exception as e:
        logger.error("orchestrate_simple failed (channel=%s): %s", channel, e)
        return "Sorry, I encountered an error. Please try again later."


# ── Post-Processing with Retry (NanoClaw group-queue pattern) ──

async def _retry_async(coro_fn, name: str, max_retries: int = 2, base_delay: float = 1.0) -> dict:
    """Execute an async coroutine with exponential backoff retry.

    Borrowed from NanoClaw group-queue.ts: 5s→10s→20s backoff pattern,
    adapted with shorter delays for post-processing tasks (1s→2s→4s).

    Returns a dict with 'success' bool and optional 'error' string.
    """
    for attempt in range(max_retries + 1):
        try:
            await coro_fn()
            return {"success": True, "name": name}
        except Exception as e:
            if attempt == max_retries:
                logger.warning("Post-process '%s' failed after %d retries: %s", name, max_retries, e)
                return {"success": False, "name": name, "error": str(e)}
            delay = base_delay * (2 ** attempt)
            logger.debug("Retrying '%s' in %.1fs (attempt %d/%d): %s", name, delay, attempt + 1, max_retries, e)
            await asyncio.sleep(delay)
    return {"success": False, "name": name, "error": "exhausted retries"}


async def _persist_pp_failures(ctx: AgentContext, db_factory, failures: list[dict]) -> None:
    """Record post-processing failures as a notification so the user can see them."""
    from models.notification import Notification

    failed_names = [f.get("name", "unknown") for f in failures]
    errors_detail = "; ".join(
        f"{f.get('name', '?')}: {f.get('error', 'unknown')[:120]}" for f in failures
    )
    async with db_factory() as db:
        notification = Notification(
            user_id=ctx.user_id,
            course_id=ctx.course_id,
            category="system",
            priority="low",
            title="Background processing partially failed",
            body=f"Some post-processing steps failed after your last chat message: {', '.join(failed_names)}. Details: {errors_detail[:300]}",
        )
        db.add(notification)
        await db.commit()
    logger.info("Persisted %d post-processing failure(s) as notification: %s", len(failures), failed_names)


async def _record_llm_usage(ctx: AgentContext, db_factory) -> None:
    """Record LLM usage event for cost tracking (fire-and-forget)."""
    try:
        async with db_factory() as db:
            from services.llm.usage import record_usage
            from services.llm.router import get_registry

            registry = get_registry()
            provider_name = registry.primary_name or "unknown"

            # Determine model name from the primary provider client
            model_name = "unknown"
            try:
                if registry.primary_name:
                    primary_client = registry.get(registry.primary_name)
                    model_name = getattr(primary_client, "model", "unknown")
            except Exception:
                pass

            await record_usage(
                db,
                user_id=ctx.user_id,
                course_id=ctx.course_id,
                agent_name=ctx.delegated_agent or ctx.metadata.get("routed_agent", "unknown"),
                scene=ctx.scene,
                model_provider=provider_name,
                model_name=model_name,
                input_tokens=ctx.input_tokens,
                output_tokens=ctx.output_tokens,
                tool_calls=len(ctx.tool_calls),
                metadata={"intent": ctx.intent.value if ctx.intent else None},
            )
    except Exception as e:
        logger.debug("Usage recording failed (non-critical): %s", e)


async def post_process(ctx: AgentContext, db_factory) -> None:
    """Async post-processing: signal extraction + memory encoding + graph extraction.

    OpenAkita Compiler pattern: lightweight async tasks after main response.
    NanoClaw retry pattern: exponential backoff on failure.
    Uses a new DB session to avoid session lifecycle issues.
    """
    ctx.transition(TaskPhase.POST_PROCESSING)
    pp_results: list[dict] = []
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

            # 5. Behavior-based preference inference (every interaction)
            async def behavior_signals():
                from services.preference.extractor import collect_behavior_signals
                from services.preference.confidence import process_signal_to_preference
                from models.preference import PreferenceSignal

                signals = await collect_behavior_signals(db, ctx.user_id, ctx.course_id)
                for signal in signals:
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
                if signals:
                    logger.info("Behavior signals inferred: %d signals", len(signals))

            # Execute sequentially — AsyncSession is NOT safe for concurrent use.
            # _retry_async returns {success, name, error?} for tracking.
            pp_results: list[dict] = []
            for coro_fn, name, retries in [
                (extract_signal, "signal_extraction", 2),
                (encode_mem, "memory_encoding", 2),
                (extract_graph, "graph_extraction", 1),
                (auto_consolidate, "auto_consolidation", 1),
                (behavior_signals, "behavior_inference", 1),
            ]:
                pp_results.append(await _retry_async(coro_fn, name, max_retries=retries))

            # Commit whatever succeeded — partial results are better than none
            await db.commit()

    except Exception as e:
        logger.warning("Post-processing failed: %s", e, exc_info=True)
        pp_results = [{"success": False, "name": "post_process_session", "error": str(e)}]

    # Persist tool calls (separate session to avoid coupling with post-processing)
    if ctx.tool_calls:
        try:
            from services.agent.tool_tracking import batch_record_tool_calls
            async with db_factory() as tool_db:
                await batch_record_tool_calls(
                    tool_db,
                    user_id=ctx.user_id,
                    course_id=ctx.course_id,
                    session_id=str(ctx.session_id) if ctx.session_id else None,
                    agent_name=ctx.delegated_agent or "unknown",
                    tool_calls=ctx.tool_calls,
                )
        except Exception as e:
            logger.warning("Failed to persist tool calls: %s", e)

    # Update tutor notes (fire-and-forget, non-critical)
    try:
        if ctx.response and ctx.user_message:
            from services.agent.tutor_notes import update_tutor_notes

            # Build a brief conversation summary from the current turn
            summary = (
                f"Student: {ctx.user_message[:300]}\n"
                f"Tutor: {ctx.response[:500]}"
            )
            current_notes = ctx.metadata.get("tutor_notes")

            async with db_factory() as notes_db:
                await update_tutor_notes(
                    notes_db,
                    ctx.user_id,
                    ctx.course_id,
                    current_notes,
                    summary,
                )
    except Exception as e:
        logger.warning("Tutor notes update failed (non-critical): %s", e)

    # Persist post-processing failures as notifications so the user sees them
    failures = [r for r in pp_results if not r.get("success")]
    if failures:
        try:
            await _persist_pp_failures(ctx, db_factory, failures)
        except Exception as e:
            logger.debug("Failed to persist post-processing failure notification: %s", e)

    # Extension hook: post-processing complete
    try:
        from services.agent.extensions import get_extension_registry, ExtensionHook
        await get_extension_registry().run_hooks(
            ExtensionHook.POST_PROCESS, ctx, response=ctx.response or "",
        )
    except Exception as e:
        logger.debug("POST_PROCESS extension hook error: %s", e)

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
    # De-duplicated fatigue signals — each concept appears in only ONE group
    # to prevent a single phrase from matching multiple patterns and inflating the score.
    FATIGUE_SIGNALS = [
        (r"(don'?t\s+want\s+to\s+study|give\s+up|so\s+annoying|so\s+tired|can'?t\s+keep\s+going|hate\s+this)", 0.35),
        (r"(can'?t\s+do\s+it|too\s+hard|frustrated|confused)", 0.3),
        (r"(can'?t\s+understand|can'?t\s+learn|why\s+still\s+wrong|wrong\s+again|can'?t\s+figure\s+out)", 0.3),
        (r"(again\s+wrong|still\s+don'?t\s+get|keep\s+getting\s+wrong|makes\s+no\s+sense)", 0.25),
        (r"(forget\s+it|sigh|ugh|whatever|nvm|never\s+mind)", 0.25),
        (r"[😫😤😩😭💀🤯😡]{1}", 0.2),
    ]
    POSITIVE_SIGNALS = [
        (r"(i\s+get\s+it|i\s+understand|so\s+that'?s\s+how|learned\s+it|mastered\s+it|got\s+it\s+done)", -0.3),
        (r"(i see|got it|makes sense|understand now|figured it out)", -0.3),
        (r"(thanks?|not\s+bad|pretty\s+good|great|nice|cool)", -0.15),
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

    # Extension hooks
    from services.agent.extensions import get_extension_registry, ExtensionHook
    ext_registry = get_extension_registry()

    # Emit agent status
    yield {"event": "status", "data": json.dumps({"phase": "routing"})}

    await ext_registry.run_hooks(ExtensionHook.PRE_ROUTING, ctx, message=message)

    ctx.transition(TaskPhase.ROUTING)
    ctx = await classify_intent(ctx)

    await ext_registry.run_hooks(
        ExtensionHook.POST_ROUTING, ctx,
        intent=ctx.intent.value, confidence=ctx.intent_confidence,
    )

    yield {
        "event": "status",
        "data": json.dumps({
            "phase": "loading",
            "intent": ctx.intent.value,
            "confidence": ctx.intent_confidence,
        }),
    }

    # 3. Load context (parallel when enabled, sequential fallback)
    ctx = await load_context(ctx, db, db_factory=db_factory)

    # Detect complex multi-step requests and submit as background task
    from services.agent.task_planner import is_complex_request
    if is_complex_request(ctx.user_message) and ctx.intent in (IntentType.PLAN, IntentType.LEARN, IntentType.REVIEW):
        try:
            from services.agent.task_planner import create_plan
            from services.activity.engine import submit_task

            plan_steps = await create_plan(ctx.user_message, ctx.user_id, ctx.course_id)
            initial_plan_progress = [
                {
                    "step_index": step["step_index"],
                    "step_type": step.get("step_type", "unknown"),
                    "title": step.get("title", f"Step {step['step_index'] + 1}"),
                    "status": "pending",
                    "depends_on": step.get("depends_on", []),
                    "agent": step.get("agent"),
                    "summary": None,
                }
                for step in plan_steps
            ]
            task = await submit_task(
                user_id=ctx.user_id,
                task_type="multi_step",
                title=f"Multi-step plan: {ctx.user_message[:100]}",
                course_id=ctx.course_id,
                source="chat",
                input_json={"steps": plan_steps, "course_id": str(ctx.course_id)},
                metadata_json={"plan_progress": initial_plan_progress, "origin_message": ctx.user_message[:300]},
            )
            yield {
                "event": "plan_step",
                "data": json.dumps({
                    "task_id": str(task.id),
                    "steps": initial_plan_progress,
                    "message": "I've created a multi-step plan for your request. It's running in the background.",
                }),
            }
            ctx.metadata["task_link"] = {
                "task_id": str(task.id),
                "task_type": task.task_type,
                "status": task.status,
            }
            ctx.delegated_agent = "coordinator"
            ctx.response = (
                "I created a background plan for this request. "
                "It will review your current progress, identify weak spots, and coordinate the next study actions. "
                "You can watch the task progress in the activity panel while continuing with the workspace."
            )
            ctx.metadata["provenance"] = _build_provenance(ctx)
            ctx.metadata["verifier"] = asdict(
                AgentVerificationResult(
                    status="pass",
                    code="background_task_created",
                    message="Complex request was converted into a durable background task.",
                )
            )
            yield {"event": "message", "data": json.dumps({"content": ctx.response})}
            yield {"event": "done", "data": json.dumps(_envelope_payload(ctx))}
            return
        except Exception as e:
            logger.warning("Multi-step planning failed, falling back to single turn: %s", e)

    fatigue = _detect_fatigue(ctx.user_message)
    if fatigue > 0.6 and "motivation" in AGENT_REGISTRY:
        agent = AGENT_REGISTRY["motivation"]
        ctx.metadata["fatigue_level"] = fatigue
    else:
        agent = get_agent(ctx.intent)
    ctx.delegated_agent = agent.name

    # ── Swarm check: should we fan-out to multiple agents in parallel? ──
    from config import settings

    swarm_plan = should_use_swarm(ctx) if settings.swarm_enabled else None

    if swarm_plan:
        # ── Parallel multi-agent (swarm) execution path ──
        ctx.swarm_mode = True
        ctx.merge_strategy = swarm_plan.merge_strategy

        yield {
            "event": "status",
            "data": json.dumps({
                "phase": "parallel_dispatch",
                "agents": [a["agent"] for a in swarm_plan.agents],
            }),
        }
        yield {
            "event": "swarm_start",
            "data": json.dumps({
                "agents": [a["agent"] for a in swarm_plan.agents],
                "reason": swarm_plan.reason,
            }),
        }

        ctx.transition(TaskPhase.PARALLEL_DISPATCH)
        branches = await agent.delegate_parallel(
            swarm_plan.agents, ctx, db_factory,
            timeout=settings.swarm_timeout_seconds,
        )

        # Token usage already aggregated by delegate_parallel()

        ctx.transition(TaskPhase.MERGING)
        yield {
            "event": "swarm_merging",
            "data": json.dumps({"strategy": swarm_plan.merge_strategy}),
        }

        merged = await merge_results(
            branches, ctx.user_message,
            strategy=swarm_plan.merge_strategy,
            primary_agent=swarm_plan.primary_agent,
        )

        # Stream the merged response in chunks
        for i in range(0, len(merged), 100):
            chunk = merged[i:i + 100]
            yield {"event": "message", "data": json.dumps({"content": chunk})}

        ctx.response = merged
        ctx.transition(TaskPhase.COMPLETED)
        ctx.metadata["provenance"] = _build_provenance(ctx)

        # Done streaming (swarm path)
        yield {
            "event": "done",
            "data": json.dumps({
                **_envelope_payload(ctx),
                "swarm": {
                    "agents": [a["agent"] for a in swarm_plan.agents],
                    "merge_strategy": swarm_plan.merge_strategy,
                    "reason": swarm_plan.reason,
                    "branches": [
                        {
                            "agent": b["agent"],
                            "success": b["success"],
                            "tokens": b["tokens"],
                            "duration_ms": b["duration_ms"],
                        }
                        for b in branches
                    ],
                },
            }),
        }

        # Post-processing (same pattern as single-agent path)
        if ctx.response:
            import copy
            swarm_bg_ctx = copy.deepcopy(ctx)
            task = asyncio.create_task(post_process(swarm_bg_ctx, db_factory))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

    else:
        # ── Single-agent execution path (existing flow) ──

        yield {
            "event": "status",
            "data": json.dumps({
                "phase": "generating",
                "agent": agent.name,
            }),
        }

        await ext_registry.run_hooks(ExtensionHook.PRE_AGENT, ctx, agent_name=agent.name)

        # 5. Stream response with marker parsing + token tracking
        # Markers: [ACTION:...] (UI actions), [TOOL_START:...] / [TOOL_DONE:...] (ReAct tools)
        buffer = ""
        async for chunk in agent.stream(ctx, db):
            buffer += chunk

            # Parse markers one at a time until no more complete markers found
            changed = True
            while changed:
                changed = False

                # Parse [TOOL_START:tool_name] or [TOOL_START:tool_name|explanation] markers
                if "[TOOL_START:" in buffer:
                    start = buffer.index("[TOOL_START:")
                    end = buffer.find("]", start)
                    if end != -1:
                        before = buffer[:start]
                        if before:
                            yield {"event": "message", "data": json.dumps({"content": before})}
                        marker_content = buffer[start + 12:end]
                        if "|" in marker_content:
                            tool_name, explanation = marker_content.split("|", 1)
                        else:
                            tool_name, explanation = marker_content, ""
                        event_data: dict = {"status": "running", "tool": tool_name}
                        if explanation:
                            event_data["explanation"] = explanation
                        yield {
                            "event": "tool_status",
                            "data": json.dumps(event_data),
                        }
                        buffer = buffer[end + 1:]
                        changed = True
                        continue

                # Parse [TOOL_DONE:tool_name] or [TOOL_DONE:tool_name|explanation] markers
                if "[TOOL_DONE:" in buffer:
                    start = buffer.index("[TOOL_DONE:")
                    end = buffer.find("]", start)
                    if end != -1:
                        before = buffer[:start]
                        if before:
                            yield {"event": "message", "data": json.dumps({"content": before})}
                        marker_content = buffer[start + 11:end]
                        if "|" in marker_content:
                            tool_name, explanation = marker_content.split("|", 1)
                        else:
                            tool_name, explanation = marker_content, ""
                        event_data = {"status": "complete", "tool": tool_name}
                        if explanation:
                            event_data["explanation"] = explanation
                        yield {
                            "event": "tool_status",
                            "data": json.dumps(event_data),
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
        await ext_registry.run_hooks(
            ExtensionHook.POST_AGENT, ctx,
            agent_name=agent.name, response=ctx.response or "",
        )
        streamed_response = ctx.response
        ctx.metadata["provenance"] = _build_provenance(ctx)
        ctx = await apply_verifier(ctx, agent)

        should_reflect = (
            bool(ctx.response)
            and ctx.intent in (IntentType.LEARN, IntentType.REVIEW)
            and len(ctx.response) > 100
        )
        if should_reflect:
            yield {"event": "status", "data": json.dumps({"phase": "verifying"})}
            ctx = await apply_reflection(ctx)
        ctx.metadata["provenance"] = _build_provenance(ctx)
        if ctx.response != streamed_response:
            yield {"event": "replace", "data": json.dumps({"content": ctx.response})}

        # Done streaming
        yield {
            "event": "done",
            "data": json.dumps(_envelope_payload(ctx)),
        }

        # Snapshot ctx for background tasks to avoid data races with the SSE generator
        import copy
        bg_ctx = copy.deepcopy(ctx)

        # 7a. Record LLM usage (fire-and-forget)
        if bg_ctx.input_tokens or bg_ctx.output_tokens:
            task_usage = asyncio.create_task(_record_llm_usage(bg_ctx, db_factory))
            _background_tasks.add(task_usage)
            task_usage.add_done_callback(_background_tasks.discard)

        # 7b. Post-processing with retry (tracked to prevent GC and enable graceful shutdown)
        if bg_ctx.response:
            task = asyncio.create_task(post_process(bg_ctx, db_factory))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
