"""Orchestrator -- central coordinator for multi-agent architecture."""

import asyncio
import json
import logging
import re
import uuid

from typing import AsyncIterator

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, IntentType, TaskPhase
from services.agent.router import classify_intent
from services.agent.base import BaseAgent
from services.agent.registry import get_agent, build_agent_context
from services.agent.context_builder import load_context
from services.agent.background_runtime import (
    enqueue_post_process_task,
    post_process,
    run_post_process_bundle,
    track_background_task,
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
from services.agent.fatigue import detect_fatigue
from services.agent.guided_session_handler import handle_guided_session

logger = logging.getLogger(__name__)

_CLARIFY_RE = re.compile(r'^\[CLARIFY:([^:]+):(.+)\]$')

_ADAPTATION_WARNING = {
    "type": "adaptation_degraded",
    "message": (
        "Advanced adaptation is temporarily unavailable for this reply. "
        "I'll keep helping, but personalized pacing and layout tuning may be reduced."
    ),
}


def _parse_clarify_inputs(message: str) -> dict[str, str]:
    """Parse clarify response from frontend.

    Supports both legacy format [CLARIFY:key:value] and JSON format
    {"type": "clarify", "key": "...", "value": "..."}.
    """
    # Try JSON format first
    stripped = message.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
            if data.get("type") == "clarify" and "key" in data and "value" in data:
                return {data["key"]: data["value"]}
        except (ValueError, KeyError):
            pass

    # Legacy bracket format
    m = _CLARIFY_RE.match(stripped)
    if m:
        return {m.group(1): m.group(2)}

    return {}


def _record_stream_warning(ctx: AgentContext, warning: dict[str, str]) -> None:
    """Attach a deduplicated warning for SSE consumers."""
    warnings = ctx.metadata.setdefault("stream_warnings", [])
    if not isinstance(warnings, list):
        warnings = []
        ctx.metadata["stream_warnings"] = warnings
    if any(existing.get("type") == warning.get("type") for existing in warnings if isinstance(existing, dict)):
        return
    warnings.append(warning)


async def _apply_turn_enrichment(ctx: AgentContext, db: AsyncSession) -> AgentContext:
    """Apply shared per-turn enrichment for stream/non-stream entry points."""
    fatigue = detect_fatigue(ctx.user_message)
    ctx.metadata["fatigue_score"] = fatigue

    try:
        if db is None:
            raise ValueError("db session unavailable for cognitive load")
        from services.cognitive_load import compute_cognitive_load

        cl = await compute_cognitive_load(
            db,
            user_id=ctx.user_id,
            course_id=ctx.course_id,
            fatigue_score=fatigue,
            session_messages=len(ctx.metadata.get("history", [])),
            user_message=ctx.user_message,
        )
        ctx.metadata["cognitive_load"] = cl
        if db is not None and cl.get("consecutive_high", 0) > 0:
            try:
                from services.agent.kv_store import kv_set

                await kv_set(
                    db,
                    ctx.user_id,
                    "cognitive_load",
                    "consecutive",
                    {"consecutive_high": cl["consecutive_high"]},
                    course_id=ctx.course_id,
                )
            except (SQLAlchemyError, ConnectionError, TimeoutError):
                logger.debug("Failed to persist cognitive load counter")
    except (SQLAlchemyError, ImportError, ConnectionError, TimeoutError, ValueError) as e:
        logger.debug("Cognitive load detection skipped: %s", e)
        _record_stream_warning(ctx, _ADAPTATION_WARNING)

    # Block Decision Engine — always run so cognitive badge state is updated.
    try:
        from services.block_decision.engine import compute_block_decisions

        block_types = ctx.metadata.get("block_types", [])
        agenda_signals: list[dict] = []
        try:
            from services.agent.signals import collect_signals

            raw_signals = await collect_signals(ctx.user_id, ctx.course_id, db)
            agenda_signals = [
                {
                    "signal_type": s.signal_type,
                    "urgency": s.urgency,
                    "detail": s.detail,
                    "title": s.title,
                }
                for s in raw_signals
            ]
        except (SQLAlchemyError, ImportError, ValueError, RuntimeError) as sig_err:
            logger.warning("Signal collection for block decisions skipped: %s", sig_err)

        block_prefs = None
        try:
            from services.block_decision.preference import compute_block_preferences

            raw_prefs = await compute_block_preferences(db, ctx.user_id, ctx.course_id)
            if raw_prefs:
                blocked = [
                    bt for bt, data in raw_prefs.items()
                    if data.get("dismiss_count", 0) >= 5 or data.get("score", 0) < -5
                ]
                block_prefs = {"block_scores": raw_prefs, "blocked": blocked}
        except (ImportError, SQLAlchemyError, ValueError) as pref_err:
            logger.warning("Block preference loading skipped: %s", pref_err)

        decisions = await compute_block_decisions(
            db,
            ctx.user_id,
            ctx.course_id,
            current_blocks=block_types,
            current_mode=ctx.learning_mode,
            cognitive_load=ctx.metadata.get("cognitive_load"),
            dismissed_types=ctx.metadata.get("dismissed_block_types", []),
            signals=agenda_signals,
            preferences=block_prefs,
        )
        ctx.metadata["block_decisions"] = decisions
    except (ImportError, SQLAlchemyError, ConnectionError, TimeoutError, ValueError, AttributeError) as e:
        logger.debug("Block decision engine skipped: %s", e)
        _record_stream_warning(ctx, _ADAPTATION_WARNING)

    return ctx


def _build_plan_progress(plan_steps: list[dict]) -> list[dict]:
    """Normalize planner output into the plan_step SSE payload shape."""
    return [
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


async def prepare_agent_turn(
    ctx: AgentContext, db: AsyncSession, db_factory=None,
) -> tuple[AgentContext, BaseAgent]:
    """Run shared orchestration steps before agent execution."""
    ctx.transition(TaskPhase.ROUTING)
    ctx = await classify_intent(ctx)
    ctx = await load_context(ctx, db, db_factory=db_factory)
    ctx = await _apply_turn_enrichment(ctx, db)

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
    clarify = _parse_clarify_inputs(message)
    if clarify:
        ctx.clarify_inputs.update(clarify)
    ctx, agent = await prepare_agent_turn(ctx, db, db_factory=db_factory)
    ctx = await consume_agent_stream(ctx, agent, db)
    finalize_token_usage(ctx, agent)
    ctx = await apply_verifier(ctx, agent)
    ctx = await apply_reflection(ctx)
    # Build provenance once after all post-processing is complete
    ctx.metadata["provenance"] = build_provenance(ctx)
    ctx.metadata["turn_envelope"] = envelope_payload(ctx)
    if ctx.response and post_process_inline:
        await post_process(ctx, db_factory)
    return ctx


async def orchestrate_simple(user_id, message: str, channel: str = "api", db=None, course_id=None) -> str:
    """Non-streaming orchestration for webhook/channel integrations."""
    from database import async_session
    try:
        async with async_session() as session:
            if course_id is None:
                from sqlalchemy import select
                from models.course import Course
                stmt = select(Course.id).where(Course.user_id == user_id).order_by(Course.updated_at.desc()).limit(1)
                result = await session.execute(stmt)
                course_id = result.scalar_one_or_none()
                if course_id is None:
                    return "You don't have any courses yet. Create one on the web app first."
            ctx = await run_agent_turn(
                user_id=user_id, course_id=course_id, message=message,
                db=session, db_factory=async_session, post_process_inline=True,
            )
            return ctx.response or "I couldn't process that. Please try again."
    except Exception as e:
        logger.exception("orchestrate_simple failed (channel=%s): %s", channel, e)
        return "Sorry, I encountered an error. Please try again later."


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
    learning_mode: str | None = None,
    block_types: list[str] | None = None,
    dismissed_block_types: list[str] | None = None,
) -> AsyncIterator[dict]:
    """Main orchestration entry point for streaming responses."""
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
        learning_mode=learning_mode,
        block_types=block_types,
        dismissed_block_types=dismissed_block_types,
    )
    clarify = _parse_clarify_inputs(message)
    if clarify:
        ctx.clarify_inputs.update(clarify)

    # Detect mock LLM client so the frontend can warn the user
    try:
        from services.llm.providers.mock_client import MockLLMClient
        from services.llm.router import get_llm_client
        primary_client = get_llm_client()
        if isinstance(primary_client, MockLLMClient):
            ctx.metadata["is_mock"] = True
    except (ImportError, RuntimeError, ConnectionError, ValueError):
        pass

    # Guided session detection (bypass normal routing)
    _gs_match = re.match(
        r"\[GUIDED_SESSION:(start|resume|pause):([a-f0-9\-]+)\]",
        message.strip(), re.IGNORECASE,
    )
    if _gs_match:
        gs_action, gs_task_id = _gs_match.group(1).lower(), _gs_match.group(2)
        async for evt in handle_guided_session(ctx, db, gs_action, gs_task_id):
            yield evt
        return

    from services.agent.extensions import get_extension_registry, ExtensionHook
    ext_registry = get_extension_registry()

    yield {"event": "status", "data": json.dumps({"phase": "routing"})}

    await ext_registry.run_hooks(ExtensionHook.PRE_ROUTING, ctx, message=message)

    ctx.transition(TaskPhase.ROUTING)
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

    ctx = await load_context(ctx, db, db_factory=db_factory)
    ctx = await _apply_turn_enrichment(ctx, db)
    emitted_warning_count = 0
    for warning in ctx.metadata.get("stream_warnings", []):
        if isinstance(warning, dict):
            yield {"event": "warning", "data": json.dumps(warning)}
            emitted_warning_count += 1

    # Complex request contract: emit one `plan_step` then continue normal chat response.
    from services.agent.task_planner import is_complex_request
    if is_complex_request(ctx.user_message) and ctx.intent in (IntentType.PLAN, IntentType.LEARN):
        try:
            from services.agent.task_planner import create_plan
            from services.activity.engine import submit_task

            plan_steps = await create_plan(ctx.user_message, ctx.user_id, ctx.course_id)
            initial_plan_progress = _build_plan_progress(plan_steps)
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
                    "message": "I've created a background plan for the detailed steps. Let me also answer your question directly.",
                }),
            }
            ctx.metadata["task_link"] = {
                "task_id": str(task.id),
                "task_type": task.task_type,
                "status": task.status,
            }
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, ImportError) as e:
            logger.exception("Multi-step planning failed, falling back to single turn: %s", e)

    agent = get_agent(ctx.intent)
    ctx.delegated_agent = agent.name

    yield {
        "event": "status",
        "data": json.dumps({
            "phase": "generating",
            "agent": agent.name,
        }),
    }

    await ext_registry.run_hooks(ExtensionHook.PRE_AGENT, ctx, agent_name=agent.name)

    parser = MarkerParser()
    _actions_emitted_set: set[int] = set()  # Track by index to prevent duplicates
    _progress_emitted = 0
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
                idx = len(ctx.actions) - 1
                _actions_emitted_set.add(idx)
                yield {"event": "action", "data": json.dumps(payload)}

        # Emit actions added by tool calls (not via parser)
        for idx in range(len(ctx.actions)):
            if idx not in _actions_emitted_set:
                _actions_emitted_set.add(idx)
                yield {"event": "action", "data": json.dumps(ctx.actions[idx])}

        while _progress_emitted < len(ctx.tool_progress):
            yield {"event": "tool_progress", "data": json.dumps(ctx.tool_progress[_progress_emitted])}
            _progress_emitted += 1

    remaining = parser.flush()
    if remaining:
        yield {"event": "message", "data": json.dumps({"content": remaining})}

    if db is not None:
        try:
            await db.commit()
        except SQLAlchemyError as commit_err:
            logger.exception("Post-stream commit failed: %s", commit_err)
            await db.rollback()

    finalize_token_usage(ctx, agent)
    await ext_registry.run_hooks(
        ExtensionHook.POST_AGENT, ctx,
        agent_name=agent.name, response=ctx.response or "",
    )
    streamed_response = ctx.response
    ctx = await apply_verifier(ctx, agent)
    new_warnings = ctx.metadata.get("stream_warnings", [])[emitted_warning_count:]
    for warning in new_warnings:
        if isinstance(warning, dict):
            yield {"event": "warning", "data": json.dumps(warning)}
            emitted_warning_count += 1

    should_reflect = (
        bool(ctx.response)
        and ctx.intent == IntentType.LEARN
        and len(ctx.response) > 100
    )
    if should_reflect:
        yield {"event": "status", "data": json.dumps({"phase": "verifying"})}
        ctx = await apply_reflection(ctx)
        new_warnings = ctx.metadata.get("stream_warnings", [])[emitted_warning_count:]
        for warning in new_warnings:
            if isinstance(warning, dict):
                yield {"event": "warning", "data": json.dumps(warning)}
                emitted_warning_count += 1
    # Build provenance once after all post-processing
    ctx.metadata["provenance"] = build_provenance(ctx)
    if ctx.response != streamed_response:
        yield {"event": "replace", "data": json.dumps({"content": ctx.response})}

    # Emit block_update event — always send cognitive state for badge, ops may be empty
    block_decisions = ctx.metadata.get("block_decisions")
    if block_decisions is not None:
        yield {
            "event": "block_update",
            "data": json.dumps(block_decisions.to_dict()),
        }

    yield {
        "event": "done",
        "data": json.dumps(envelope_payload(ctx)),
    }

    bg_ctx = ctx.snapshot_for_postprocess()

    if bg_ctx.response or bg_ctx.input_tokens or bg_ctx.output_tokens:
        try:
            await enqueue_post_process_task(bg_ctx)
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
            logger.exception("Failed to enqueue durable chat post-process task: %s", exc)
            track_background_task(asyncio.create_task(run_post_process_bundle(bg_ctx, db_factory)))
