"""Background execution engine for durable agent tasks.

This module is the main entry point: it contains the worker loop
(start/stop) and re-exports every public symbol from the submodules
so that existing ``from services.activity.engine import X`` imports
continue to work.

Submodules
----------
- engine_helpers   -- pure utility functions, exception classes
- engine_lifecycle -- task state mutations (approve/reject/cancel/resume/retry)
- engine_execution -- dispatch, execute, mark success/failure/cancelled
- engine_multistep -- multi-step plan execution, goal sync, auto-repair
- engine_queries   -- submit_task, claim tasks, drain_once
"""

from __future__ import annotations

import asyncio
import logging

from config import settings
from services.activity.redis_notify import (
    close_redis as _close_redis_notify,
    wait_for_task_notification,
)

# ── Re-exports from engine_helpers ────────────────────────────────
from services.activity.engine_helpers import (  # noqa: F401
    TaskCancelledError,
    TaskMutationError,
    _build_checkpoint,
    _build_plan_progress,
    _build_plan_result_payload,
    _build_plan_result_snapshot,
    _build_plan_summary,
    _coerce_step_results,
    _extract_first_action,
    _merge_step_provenance,
    _normalize_uuid,
    _queueable_status,
    _refresh_task_checkpoint,
    _refresh_task_policy,
    _serialize_goal_update,
    _task_audit_details,
    _task_event,
)

# ── Re-exports from engine_lifecycle ──────────────────────────────
from services.activity.engine_lifecycle import (  # noqa: F401
    _commit_refreshed_task,
    _get_user_task,
    _null_async_context,
    _record_task_audit,
    _task_session,
    approve_task,
    cancel_task,
    reject_task,
    resume_task,
    retry_task,
)

# ── Re-exports from engine_execution ─────────────────────────────
from services.activity.engine_execution import (  # noqa: F401
    _dispatch_task,
    _mark_task_cancelled,
    _mark_task_failure,
    _mark_task_success,
    execute_task,
)

# ── Re-exports from engine_multistep ────────────────────────────
from services.activity.engine_multistep import (  # noqa: F401
    _cancel_requested,
    _persist_plan_progress,
    _queue_auto_repair_follow_up,
    _run_multi_step_plan,
    _sync_goal_after_task_success,
)

# ── Re-exports from engine_queries ────────────────────────────────
from services.activity.engine_queries import (  # noqa: F401
    _claim_pending_tasks,
    drain_once,
    submit_task,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 1.0
IDLE_INTERVAL_SECONDS = 2.0
MAX_IDLE_INTERVAL_SECONDS = 30.0
BACKOFF_MULTIPLIER = 1.5

# ── Module-level worker state ────────────────────────────────────
_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
_worker_semaphore: asyncio.Semaphore | None = None
_inflight_tasks: set[asyncio.Task] = set()


# ── Worker helpers ────────────────────────────────────────────────

async def _execute_with_semaphore(task_id) -> None:
    """Execute a single task while holding the worker semaphore."""
    assert _worker_semaphore is not None
    async with _worker_semaphore:
        await execute_task(task_id)


async def _wait_with_redis_or_stop(timeout: float) -> bool:
    """Wait for either a Redis task notification or a stop event.

    Returns *True* if a Redis notification was received (meaning new work is
    likely available), *False* if the stop event fired or the timeout expired.
    """
    assert _stop_event is not None

    async def _redis_wait() -> bool:
        result = await wait_for_task_notification(timeout=timeout)
        return result is not None

    async def _stop_wait() -> bool:
        await _stop_event.wait()
        return False

    done, pending = await asyncio.wait(
        [asyncio.create_task(_redis_wait()), asyncio.create_task(_stop_wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    # Cancel whichever coroutine lost the race.
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, RuntimeError, OSError):
            pass
    # Return the result of the first completed coroutine.
    for task in done:
        try:
            return task.result()
        except Exception as e:
            logger.debug("Redis/stop wait task raised: %s", e)
            return False
    return False


# ── Main worker loop ──────────────────────────────────────────────

async def _run_loop() -> None:
    assert _stop_event is not None
    assert _worker_semaphore is not None
    max_concurrency = settings.activity_engine_max_concurrency
    use_redis = settings.activity_use_redis_notify

    current_idle_interval = IDLE_INTERVAL_SECONDS
    while not _stop_event.is_set():
        try:
            # Claim up to max_concurrency tasks in one batch.
            ids = await _claim_pending_tasks(max_concurrency)
        except Exception as e:
            logger.exception("Activity engine: failed to claim tasks: %s", e)
            ids = []

        if ids:
            for task_id in ids:
                t = asyncio.create_task(_execute_with_semaphore(task_id))
                _inflight_tasks.add(t)
                t.add_done_callback(_inflight_tasks.discard)
            # Reset backoff when work is found
            current_idle_interval = IDLE_INTERVAL_SECONDS
            timeout = POLL_INTERVAL_SECONDS
        else:
            # Exponential backoff when idle to reduce unnecessary DB load
            timeout = current_idle_interval
            current_idle_interval = min(current_idle_interval * BACKOFF_MULTIPLIER, MAX_IDLE_INTERVAL_SECONDS)

        # When Redis notify is enabled, use pub/sub to wait for a wake-up
        # signal instead of sleeping for the full timeout.  If a notification
        # arrives we reset the backoff and immediately loop back to claim
        # tasks.  The existing stop_event is checked concurrently so that
        # shutdown requests are still honoured promptly.
        if use_redis and not ids:
            notified = await _wait_with_redis_or_stop(timeout)
            if notified:
                # A task was published -- reset backoff and claim immediately.
                current_idle_interval = IDLE_INTERVAL_SECONDS
            continue

        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            continue


# ── Public start / stop ───────────────────────────────────────────

def start_activity_engine() -> None:
    global _worker_task, _stop_event, _worker_semaphore
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_semaphore = asyncio.Semaphore(settings.activity_engine_max_concurrency)
    _worker_task = asyncio.create_task(_run_loop())
    logger.info(
        "Activity engine started (max_concurrency=%d, redis_notify=%s)",
        settings.activity_engine_max_concurrency,
        settings.activity_use_redis_notify,
    )


async def stop_activity_engine() -> None:
    global _worker_task, _stop_event, _worker_semaphore
    if not _worker_task:
        return
    if _stop_event is not None:
        _stop_event.set()
    try:
        # Wait for the polling loop to exit.
        await _worker_task
    finally:
        _worker_task = None
        _stop_event = None
    # Drain any in-flight concurrent tasks that were already dispatched.
    if _inflight_tasks:
        logger.info("Waiting for %d in-flight task(s) to finish...", len(_inflight_tasks))
        await asyncio.gather(*_inflight_tasks, return_exceptions=True)
    _inflight_tasks.clear()
    _worker_semaphore = None
    # Close the shared Redis connection used for task notifications.
    await _close_redis_notify()
    logger.info("Activity engine stopped")
