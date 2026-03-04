"""Background task orchestration for agent post-processing."""

from __future__ import annotations

import asyncio
import logging
import uuid

from services.agent.state import AgentContext, TaskPhase

logger = logging.getLogger(__name__)

_background_tasks: set[asyncio.Task] = set()


def track_background_task(task: asyncio.Task) -> asyncio.Task:
    """Register a fire-and-forget task for graceful shutdown tracking."""
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


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


async def _retry_async(coro_fn, name: str, max_retries: int = 2, base_delay: float = 1.0) -> dict:
    """Execute an async coroutine with exponential backoff retry."""
    for attempt in range(max_retries + 1):
        try:
            await coro_fn()
            return {"success": True, "name": name}
        except Exception as exc:
            if attempt == max_retries:
                logger.warning("Post-process '%s' failed after %d retries: %s", name, max_retries, exc)
                return {"success": False, "name": name, "error": str(exc)}
            delay = base_delay * (2 ** attempt)
            logger.debug("Retrying '%s' in %.1fs (attempt %d/%d): %s", name, delay, attempt + 1, max_retries, exc)
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
            body=(
                "Some post-processing steps failed after your last chat message: "
                f"{', '.join(failed_names)}. Details: {errors_detail[:300]}"
            ),
        )
        db.add(notification)
        await db.commit()
    logger.info("Persisted %d post-processing failure(s) as notification: %s", len(failures), failed_names)


async def record_llm_usage(ctx: AgentContext, db_factory) -> None:
    """Record LLM usage event for cost tracking (fire-and-forget)."""
    try:
        async with db_factory() as db:
            from services.llm.usage import record_usage
            from services.llm.router import get_registry

            registry = get_registry()
            provider_name = registry.primary_name or "unknown"

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
    except Exception as exc:
        logger.debug("Usage recording failed (non-critical): %s", exc)


async def post_process(ctx: AgentContext, db_factory) -> None:
    """Async post-processing: signal extraction + memory encoding + graph extraction."""
    ctx.transition(TaskPhase.POST_PROCESSING)
    pp_results: list[dict] = []

    async def _signal_with_session():
        async with db_factory() as db:
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
            await db.commit()
            logger.info("Signal extracted: dim=%s val=%s", signal["dimension"], signal["value"])

    async def _memory_with_session():
        async with db_factory() as db:
            from services.memory.pipeline import encode_memory
            await encode_memory(db, ctx.user_id, ctx.course_id, ctx.user_message, ctx.response)
            await db.commit()

    async def _graph_with_session():
        async with db_factory() as db:
            from services.knowledge.graph_memory import extract_graph_entities, store_graph_entities
            extracted = await extract_graph_entities(ctx.user_message, ctx.response)
            if extracted.get("entities") or extracted.get("relationships"):
                await store_graph_entities(db, ctx.user_id, ctx.course_id, extracted)
                await db.commit()

    async def _experiment_metric_with_session():
        exp_config = ctx.metadata.get("experiment_config")
        if not exp_config:
            return
        async with db_factory() as db:
            from services.experiment.engine import record_metric

            response_score = min(1.0, len(ctx.response or "") / 1000.0)
            tool_score = min(1.0, len(ctx.tool_calls) / 5.0)
            metric_value = response_score * 0.7 + tool_score * 0.3
            await record_metric(
                db,
                experiment_id=uuid.UUID(exp_config["experiment_id"]),
                user_id=ctx.user_id,
                variant_id=exp_config["variant_id"],
                metric_name="engagement",
                metric_value=metric_value,
                metadata={
                    "intent": ctx.intent.value if ctx.intent else None,
                    "agent": ctx.delegated_agent,
                    "response_len": len(ctx.response or ""),
                    "tool_calls": len(ctx.tool_calls),
                },
            )
            await db.commit()

    try:
        pp_results.extend(await asyncio.gather(
            _retry_async(_signal_with_session, "signal_extraction", max_retries=2),
            _retry_async(_memory_with_session, "memory_encoding", max_retries=2),
            _retry_async(_graph_with_session, "graph_extraction", max_retries=1),
            _retry_async(_experiment_metric_with_session, "experiment_metric", max_retries=1),
        ))
    except Exception as exc:
        logger.warning("Phase 1 post-processing failed: %s", exc, exc_info=True)
        pp_results.append({"success": False, "name": "parallel_phase", "error": str(exc)})

    try:
        async with db_factory() as db:
            async def auto_consolidate():
                from services.agent.memory_agent import maybe_auto_consolidate
                await maybe_auto_consolidate(db, ctx.user_id, ctx.course_id)

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

            for coro_fn, name, retries in [
                (auto_consolidate, "auto_consolidation", 1),
                (behavior_signals, "behavior_inference", 1),
            ]:
                pp_results.append(await _retry_async(coro_fn, name, max_retries=retries))

            await db.commit()
    except Exception as exc:
        logger.warning("Phase 2 post-processing failed: %s", exc, exc_info=True)
        pp_results.append({"success": False, "name": "sequential_phase", "error": str(exc)})

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
        except Exception as exc:
            logger.warning("Failed to persist tool calls: %s", exc)

    try:
        if ctx.response and ctx.user_message:
            from services.agent.tutor_notes import (
                check_and_increment_turn,
                reset_turn_counter,
                update_tutor_notes,
            )

            async with db_factory() as notes_db:
                do_update = await check_and_increment_turn(notes_db, ctx.user_id, ctx.course_id)
                if do_update:
                    summary = (
                        f"Student: {ctx.user_message[:300]}\n"
                        f"Tutor: {ctx.response[:500]}"
                    )
                    current_notes = ctx.metadata.get("tutor_notes")
                    await update_tutor_notes(
                        notes_db,
                        ctx.user_id,
                        ctx.course_id,
                        current_notes,
                        summary,
                    )
                    await reset_turn_counter(notes_db, ctx.user_id, ctx.course_id)
    except Exception as exc:
        logger.warning("Tutor notes update failed (non-critical): %s", exc)

    failures = [result for result in pp_results if not result.get("success")]
    if failures:
        try:
            await _persist_pp_failures(ctx, db_factory, failures)
        except Exception as exc:
            logger.debug("Failed to persist post-processing failure notification: %s", exc)

    try:
        from services.agent.extensions import ExtensionHook, get_extension_registry
        await get_extension_registry().run_hooks(
            ExtensionHook.POST_PROCESS, ctx, response=ctx.response or "",
        )
    except Exception as exc:
        logger.debug("POST_PROCESS extension hook error: %s", exc)

    ctx.mark_completed()
