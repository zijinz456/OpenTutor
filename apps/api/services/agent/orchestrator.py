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

from services.agent.state import AgentContext, AgentVerificationResult, IntentType, TaskPhase
from services.agent.router import classify_intent
from services.agent.base import BaseAgent
from services.agent.registry import AGENT_REGISTRY, get_agent, build_agent_context
from services.agent.context_builder import load_context
from services.agent.parallel import should_use_swarm, merge_results
from services.agent.background_runtime import (
    enqueue_post_process_task,
    run_post_process_bundle,
    track_background_task,
    wait_for_background_tasks,
)
from services.agent.turn_pipeline import (
    apply_reflection,
    apply_verifier,
    build_provenance,
    consume_agent_stream,
    envelope_payload,
    finalize_token_usage,
)
from services.agent.marker_parser import MarkerParser

logger = logging.getLogger(__name__)

# Backward-compatible exports for tests and adjacent modules that still import
# the legacy helper names from orchestrator.py.
_build_provenance = build_provenance
_envelope_payload = envelope_payload

# ── Pre-task clarification helpers (OpenClaw Inputs pattern) ──
_CLARIFY_RE = re.compile(r"^\[CLARIFY:(\w+):(.+)\]$")


def _extract_clarify_response(message: str) -> tuple[str, str] | None:
    """Check if message is a clarification response. Returns (key, value) or None."""
    match = _CLARIFY_RE.match(message.strip())
    if match:
        return match.group(1), match.group(2)
    return None


def _infer_previous_intent(history: list[dict]) -> IntentType | None:
    """Look at conversation history to find the most recent intent for clarify re-routing."""
    for msg in reversed(history):
        meta = msg.get("metadata") or {}
        intent_str = meta.get("intent")
        if intent_str:
            try:
                return IntentType(intent_str)
            except ValueError:
                continue
    return None


# load_context imported from services.agent.context_builder

async def prepare_agent_turn(
    ctx: AgentContext, db: AsyncSession, db_factory=None,
) -> tuple[AgentContext, BaseAgent]:
    """Run shared orchestration steps before agent execution."""
    ctx.transition(TaskPhase.ROUTING)
    ctx = await classify_intent(ctx)
    ctx = await load_context(ctx, db, db_factory=db_factory)

    fatigue = _detect_fatigue(ctx.user_message)
    ctx.metadata["fatigue_score"] = fatigue  # Phase 4: expose for Socratic guardrails
    if fatigue > 0.6 and "motivation" in AGENT_REGISTRY:
        agent = AGENT_REGISTRY["motivation"]
        ctx.metadata["fatigue_level"] = fatigue
    else:
        agent = get_agent(ctx.intent)
    ctx.delegated_agent = agent.name
    return ctx, agent


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
    ctx = await consume_agent_stream(ctx, agent, db)
    finalize_token_usage(ctx, agent)
    ctx.metadata["provenance"] = build_provenance(ctx)
    ctx = await apply_verifier(ctx, agent)
    ctx = await apply_reflection(ctx)
    ctx.metadata["provenance"] = build_provenance(ctx)
    ctx.metadata["turn_envelope"] = envelope_payload(ctx)
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


# ── Fatigue Detection (OpenAkita Persona pattern) ──
# Pre-compiled regex patterns for fatigue/positive signals (avoid re-compiling per call).
# De-duplicated fatigue signals — each concept appears in only ONE group
# to prevent a single phrase from matching multiple patterns and inflating the score.
_FATIGUE_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(don'?t\s+want\s+to\s+study|give\s+up|so\s+annoying|so\s+tired|can'?t\s+keep\s+going|hate\s+this)", re.IGNORECASE), 0.35),
    (re.compile(r"(can'?t\s+do\s+it|too\s+hard|frustrated|confused)", re.IGNORECASE), 0.3),
    (re.compile(r"(can'?t\s+understand|can'?t\s+learn|why\s+still\s+wrong|wrong\s+again|can'?t\s+figure\s+out)", re.IGNORECASE), 0.3),
    (re.compile(r"(again\s+wrong|still\s+don'?t\s+get|keep\s+getting\s+wrong|makes\s+no\s+sense)", re.IGNORECASE), 0.25),
    (re.compile(r"(forget\s+it|sigh|ugh|whatever|nvm|never\s+mind)", re.IGNORECASE), 0.25),
    (re.compile(r"[😫😤😩😭💀🤯😡]"), 0.2),
]
_POSITIVE_SIGNALS: list[tuple[re.Pattern, float]] = [
    (re.compile(r"(i\s+get\s+it|i\s+understand|so\s+that'?s\s+how|learned\s+it|mastered\s+it|got\s+it\s+done)", re.IGNORECASE), -0.3),
    (re.compile(r"(i see|got it|makes sense|understand now|figured it out)", re.IGNORECASE), -0.3),
    (re.compile(r"(thanks?|not\s+bad|pretty\s+good|great|nice|cool)", re.IGNORECASE), -0.15),
]


def _detect_fatigue(message: str) -> float:
    """Detect student frustration/fatigue level (0.0-1.0).

    OpenAkita persona dimension pattern: check signals across multiple categories.
    Positive signals reduce the score to prevent false positives.
    """
    score = 0.0
    for pattern, weight in _FATIGUE_SIGNALS:
        if pattern.search(message):
            score += weight
    for pattern, weight in _POSITIVE_SIGNALS:
        if pattern.search(message):
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

    # ── Pre-task clarification: detect [CLARIFY:key:value] responses ──
    clarify_result = _extract_clarify_response(ctx.user_message)
    if clarify_result:
        clarify_key, clarify_value = clarify_result
        ctx.clarify_inputs[clarify_key] = clarify_value
        # Reuse previous intent so we don't classify "[CLARIFY:...]" text as GENERAL
        prev_intent = _infer_previous_intent(ctx.conversation_history)
        if prev_intent:
            ctx.intent = prev_intent
            ctx.intent_confidence = 0.95
            ctx.metadata["is_clarify_response"] = True
            ctx.metadata["clarify_reused_intent"] = prev_intent.value
        # If no prev_intent found, let normal classification run (is_clarify_response stays unset)

    # Emit agent status
    yield {"event": "status", "data": json.dumps({"phase": "routing"})}

    await ext_registry.run_hooks(ExtensionHook.PRE_ROUTING, ctx, message=message)

    ctx.transition(TaskPhase.ROUTING)
    if not ctx.metadata.get("is_clarify_response"):
        ctx = await classify_intent(ctx)

    await ext_registry.run_hooks(
        ExtensionHook.POST_ROUTING, ctx,
        intent=ctx.intent.value, confidence=ctx.intent_confidence,
        agent_name=get_agent(ctx.intent).name,
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
            ctx.metadata["provenance"] = build_provenance(ctx)
            ctx.metadata["verifier"] = asdict(
                AgentVerificationResult(
                    status="pass",
                    code="background_task_created",
                    message="Complex request was converted into a durable background task.",
                )
            )
            yield {"event": "message", "data": json.dumps({"content": ctx.response})}
            yield {"event": "done", "data": json.dumps(envelope_payload(ctx))}
            return
        except Exception as e:
            logger.warning("Multi-step planning failed, falling back to single turn: %s", e)

    fatigue = _detect_fatigue(ctx.user_message)
    ctx.metadata["fatigue_score"] = fatigue  # Phase 4: expose for Socratic guardrails in base.py
    if fatigue > 0.6 and "motivation" in AGENT_REGISTRY:
        agent = AGENT_REGISTRY["motivation"]
        ctx.metadata["fatigue_level"] = fatigue
    else:
        agent = get_agent(ctx.intent)
    ctx.delegated_agent = agent.name

    # ── Pre-task questioning: check if agent needs clarification inputs ──
    if not ctx.metadata.get("is_clarify_response"):
        required_inputs = agent.get_required_inputs()
        if required_inputs:
            missing = [inp for inp in required_inputs if not inp.check(ctx)]
            if missing:
                first_missing = missing[0]  # Ask one question at a time
                clarify_msg = f"{first_missing.question}\n\n_(You can also just tell me in your own words!)_"
                yield {
                    "event": "clarify",
                    "data": json.dumps({
                        "key": first_missing.key,
                        "question": first_missing.question,
                        "options": first_missing.options,
                        "agent": agent.name,
                        "total_missing": len(missing),
                    }),
                }
                yield {"event": "message", "data": json.dumps({"content": clarify_msg})}
                ctx.response = clarify_msg
                ctx.metadata["clarify_pending"] = [inp.key for inp in missing]
                ctx.metadata["provenance"] = build_provenance(ctx)
                yield {"event": "done", "data": json.dumps(envelope_payload(ctx))}
                return

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
        ctx.metadata["provenance"] = build_provenance(ctx)

        # Done streaming (swarm path)
        yield {
            "event": "done",
            "data": json.dumps({
                **envelope_payload(ctx),
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
            swarm_bg_ctx = ctx.snapshot_for_postprocess()
            try:
                await enqueue_post_process_task(swarm_bg_ctx)
            except Exception as exc:
                logger.warning("Failed to enqueue durable swarm post-process task: %s", exc)
                track_background_task(asyncio.create_task(run_post_process_bundle(swarm_bg_ctx, db_factory)))

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
        parser = MarkerParser()
        _actions_emitted = 0   # Track actions already sent as SSE events
        _progress_emitted = 0  # Track progress events already sent
        async for chunk in agent.stream(ctx, db):
            for event_type, payload in parser.feed(chunk):
                if event_type == "text":
                    yield {"event": "message", "data": json.dumps({"content": payload})}
                elif event_type == "tool_start":
                    event_data: dict = {"status": "running", "tool": payload["tool"]}
                    if payload["explanation"]:
                        event_data["explanation"] = payload["explanation"]
                    yield {"event": "tool_status", "data": json.dumps(event_data)}
                elif event_type == "tool_done":
                    event_data = {"status": "complete", "tool": payload["tool"]}
                    if payload["explanation"]:
                        event_data["explanation"] = payload["explanation"]
                    yield {"event": "tool_status", "data": json.dumps(event_data)}
                elif event_type == "action":
                    ctx.actions.append(payload)
                    _actions_emitted += 1
                    yield {"event": "action", "data": json.dumps(payload)}

            # Emit actions appended directly by tools (not via text markers)
            while _actions_emitted < len(ctx.actions):
                yield {"event": "action", "data": json.dumps(ctx.actions[_actions_emitted])}
                _actions_emitted += 1

            # Emit tool progress events added by write tools
            while _progress_emitted < len(ctx.tool_progress):
                yield {"event": "tool_progress", "data": json.dumps(ctx.tool_progress[_progress_emitted])}
                _progress_emitted += 1

        remaining = parser.flush()
        if remaining:
            yield {"event": "message", "data": json.dumps({"content": remaining})}

        # Commit write-tool changes atomically (tools use flush, orchestrator commits)
        if ctx.tool_calls:
            try:
                await db.commit()
            except Exception as commit_err:
                logger.error("Post-stream commit failed: %s", commit_err)
                await db.rollback()

        finalize_token_usage(ctx, agent)
        await ext_registry.run_hooks(
            ExtensionHook.POST_AGENT, ctx,
            agent_name=agent.name, response=ctx.response or "",
        )
        streamed_response = ctx.response
        ctx.metadata["provenance"] = build_provenance(ctx)
        ctx = await apply_verifier(ctx, agent)

        should_reflect = (
            bool(ctx.response)
            and ctx.intent in (IntentType.LEARN, IntentType.REVIEW)
            and len(ctx.response) > 100
        )
        if should_reflect:
            yield {"event": "status", "data": json.dumps({"phase": "verifying"})}
            ctx = await apply_reflection(ctx)
        ctx.metadata["provenance"] = build_provenance(ctx)
        if ctx.response != streamed_response:
            yield {"event": "replace", "data": json.dumps({"content": ctx.response})}

        # Done streaming
        yield {
            "event": "done",
            "data": json.dumps(envelope_payload(ctx)),
        }

        # Lightweight snapshot for background tasks (avoids deep-copying large context fields)
        bg_ctx = ctx.snapshot_for_postprocess()

        if bg_ctx.response or bg_ctx.input_tokens or bg_ctx.output_tokens:
            try:
                await enqueue_post_process_task(bg_ctx)
            except Exception as exc:
                logger.warning("Failed to enqueue durable chat post-process task: %s", exc)
                track_background_task(asyncio.create_task(run_post_process_bundle(bg_ctx, db_factory)))
