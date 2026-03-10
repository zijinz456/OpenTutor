"""Orchestrator -- central coordinator for multi-agent architecture."""

import asyncio
import json
import logging
import re
import uuid

from sqlalchemy.exc import SQLAlchemyError
from dataclasses import asdict
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.state import AgentContext, AgentVerificationResult, IntentType, TaskPhase
from services.agent.router import classify_intent
from services.agent.base import BaseAgent
from services.agent.registry import AGENT_REGISTRY, get_agent, build_agent_context
from services.agent.context_builder import load_context
from services.agent.background_runtime import (
    enqueue_post_process_task,
    post_process,
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
from services.agent.fatigue import detect_fatigue
from services.agent.guided_session_handler import handle_guided_session

logger = logging.getLogger(__name__)

# Backward-compatible exports for tests and adjacent modules
_build_provenance = build_provenance
_envelope_payload = envelope_payload
_detect_fatigue = detect_fatigue
_handle_guided_session = handle_guided_session


async def prepare_agent_turn(
    ctx: AgentContext, db: AsyncSession, db_factory=None,
) -> tuple[AgentContext, BaseAgent]:
    """Run shared orchestration steps before agent execution."""
    ctx.transition(TaskPhase.ROUTING)
    ctx = await classify_intent(ctx)
    ctx = await load_context(ctx, db, db_factory=db_factory)

    fatigue = _detect_fatigue(ctx.user_message)
    ctx.metadata["fatigue_score"] = fatigue

    try:
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
    except (SQLAlchemyError, ImportError, ConnectionError, TimeoutError, ValueError, AttributeError) as e:
        logger.debug("Cognitive load detection skipped: %s", e)

    # Block Decision Engine — evaluate all signals against current layout
    # Always runs (even with empty blocks) so cognitive state badge stays updated
    try:
        from services.block_decision.engine import compute_block_decisions
        block_types = ctx.metadata.get("block_types", [])

        # Collect agenda signals for richer decisions
        agenda_signals: list[dict] = []
        try:
            from services.agent.signals import collect_signals
            raw_signals = await collect_signals(ctx.user_id, ctx.course_id, db)
            agenda_signals = [
                {"signal_type": s.signal_type, "urgency": s.urgency,
                 "detail": s.detail, "title": s.title}
                for s in raw_signals
            ]
        except (SQLAlchemyError, ImportError, ValueError, RuntimeError) as sig_err:
            logger.debug("Signal collection for block decisions skipped: %s", sig_err)

        # Load user's block preferences for filtering
        block_prefs = None
        try:
            from services.block_decision.preference import compute_block_preferences
            raw_prefs = await compute_block_preferences(db, ctx.user_id, ctx.course_id)
            if raw_prefs:
                block_prefs = {"block_scores": raw_prefs}
        except (ImportError, SQLAlchemyError, ValueError) as pref_err:
            logger.debug("Block preference loading skipped: %s", pref_err)

        decisions = await compute_block_decisions(
            db, ctx.user_id, ctx.course_id,
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

    # Guided session detection (bypass normal routing)
    _gs_match = re.match(
        r"\[GUIDED_SESSION:(start|resume|pause):([a-f0-9\-]+)\]",
        message.strip(), re.IGNORECASE,
    )
    if _gs_match:
        gs_action, gs_task_id = _gs_match.group(1).lower(), _gs_match.group(2)
        async for evt in _handle_guided_session(ctx, db, gs_action, gs_task_id):
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

    # Detect complex multi-step requests
    from services.agent.task_planner import is_complex_request
    if is_complex_request(ctx.user_message) and ctx.intent in (IntentType.PLAN, IntentType.LEARN):
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
        except (SQLAlchemyError, ConnectionError, TimeoutError, ValueError, RuntimeError, ImportError) as e:
            logger.exception("Multi-step planning failed, falling back to single turn: %s", e)

    fatigue = _detect_fatigue(ctx.user_message)
    ctx.metadata["fatigue_score"] = fatigue

    try:
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
        # NOTE: layout_simplification removed — Block Decision Engine (block_update event)
        # now handles cognitive overload via rule_cognitive_overload in prepare_agent_turn.
        if cl.get("consecutive_high", 0) > 0:
            try:
                from services.agent.kv_store import kv_set
                await kv_set(
                    db, ctx.user_id, "cognitive_load", "consecutive",
                    {"consecutive_high": cl["consecutive_high"]},
                    course_id=ctx.course_id,
                )
            except (SQLAlchemyError, ConnectionError, TimeoutError):
                logger.debug("Failed to persist cognitive load counter")
    except (SQLAlchemyError, ImportError, ConnectionError, TimeoutError, ValueError, AttributeError) as e:
        logger.debug("Cognitive load detection skipped: %s", e)

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
    _actions_emitted = 0
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
                _actions_emitted += 1
                yield {"event": "action", "data": json.dumps(payload)}

        while _actions_emitted < len(ctx.actions):
            yield {"event": "action", "data": json.dumps(ctx.actions[_actions_emitted])}
            _actions_emitted += 1

        while _progress_emitted < len(ctx.tool_progress):
            yield {"event": "tool_progress", "data": json.dumps(ctx.tool_progress[_progress_emitted])}
            _progress_emitted += 1

    remaining = parser.flush()
    if remaining:
        yield {"event": "message", "data": json.dumps({"content": remaining})}

    if ctx.tool_calls:
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
    ctx.metadata["provenance"] = build_provenance(ctx)
    ctx = await apply_verifier(ctx, agent)

    should_reflect = (
        bool(ctx.response)
        and ctx.intent == IntentType.LEARN
        and len(ctx.response) > 100
    )
    if should_reflect:
        yield {"event": "status", "data": json.dumps({"phase": "verifying"})}
        ctx = await apply_reflection(ctx)
    ctx.metadata["provenance"] = build_provenance(ctx)
    if ctx.response != streamed_response:
        yield {"event": "replace", "data": json.dumps({"content": ctx.response})}

    # Emit block_update event — always send cognitive state for badge, ops may be empty
    block_decisions = ctx.metadata.get("block_decisions")
    if block_decisions:
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
