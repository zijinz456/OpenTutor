"""Scheduler maintenance jobs — core agent loop and infrastructure tasks.

Jobs:
- agenda_tick_job       — unified proactive agent loop (every 2 hours)
- weekly_prep_job       — weekly study prep (Monday 8:00 AM)
- scrape_refresh_job    — auto-scrape refresh (every hour)
- memory_consolidation_job — dedup/decay/categorize (every 6 hours)
- timing_analysis_job   — no-op stub
- escalation_check_job  — no-op stub
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from database import async_session
from models.agent_task import AgentTask
from models.study_goal import StudyGoal
from services.activity.engine import submit_task
from services.provenance import build_provenance
from services.scheduler.engine_helpers import _get_user_ids, _push_notification

logger = logging.getLogger(__name__)


# ── Weekly prep helpers ──────────────────────────────────────────────


async def _get_or_create_weekly_review_goal(
    db,
    user_id: uuid.UUID,
    week_start: datetime,
) -> StudyGoal:
    result = await db.execute(
        select(StudyGoal)
        .where(
            StudyGoal.user_id == user_id,
            StudyGoal.status == "active",
            StudyGoal.course_id.is_(None),
        )
        .order_by(StudyGoal.created_at.asc())
    )
    goals = result.scalars().all()
    for goal in goals:
        metadata = goal.metadata_json or {}
        if metadata.get("goal_kind") == "weekly_review":
            goal.target_date = week_start + timedelta(days=6)
            goal.metadata_json = {
                **metadata,
                "system_managed": True,
            }
            await db.commit()
            await db.refresh(goal)
            return goal

    goal = StudyGoal(
        user_id=user_id,
        course_id=None,
        title="Stay on track this week",
        objective="Refresh priorities every week, review deadlines, and keep one clear next study action active.",
        success_metric="Complete a weekly review and keep the next action current.",
        current_milestone="Weekly review queue initialized",
        next_action="Review this week's queued study task.",
        status="active",
        confidence="system",
        target_date=week_start + timedelta(days=6),
        metadata_json={"goal_kind": "weekly_review", "system_managed": True},
    )
    db.add(goal)
    await db.commit()
    await db.refresh(goal)
    return goal


async def _has_scheduled_weekly_task(
    db,
    user_id: uuid.UUID,
    goal_id: uuid.UUID,
    week_start: datetime,
) -> bool:
    result = await db.execute(
        select(AgentTask)
        .where(
            AgentTask.user_id == user_id,
            AgentTask.goal_id == goal_id,
            AgentTask.task_type == "weekly_prep",
            AgentTask.source == "scheduler",
            AgentTask.created_at >= week_start,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


# ── Jobs ─────────────────────────────────────────────────────────────


async def weekly_prep_job():
    """Weekly prep job — triggers WF-2 for all users every Monday."""
    logger.info("Running weekly prep job...")
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

    user_ids = await _get_user_ids()
    for user_id in user_ids:
        try:
            async with async_session() as db:
                goal = await _get_or_create_weekly_review_goal(db, user_id, week_start)
                if await _has_scheduled_weekly_task(db, user_id, goal.id, week_start):
                    continue
                await submit_task(
                    user_id=user_id,
                    goal_id=goal.id,
                    task_type="weekly_prep",
                    title=f"Weekly review for {week_start.date().isoformat()}",
                    summary="Scheduler queued a weekly review to refresh your study plan and next action.",
                    source="scheduler",
                    input_json={
                        "trigger": "weekly_scheduler",
                        "week_start": week_start.date().isoformat(),
                    },
                    metadata_json={
                        "provenance": build_provenance(
                            workflow="weekly_prep",
                            generated=True,
                            source_labels=["workflow", "generated", "scheduler"],
                            scheduler_trigger="weekly_scheduler",
                        ),
                        "scheduler": {
                            "job": "weekly_prep",
                            "week_start": week_start.date().isoformat(),
                        },
                    },
                    max_attempts=2,
                )
            await _push_notification(
                user_id,
                "Weekly Review Queued",
                "OpenTutor queued your weekly review task. Approve or inspect it from the activity panel once it starts.",
                category="weekly_prep",
            )
        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
            logger.exception("Weekly prep failed for user %s", user_id)


async def agenda_tick_job():
    """Unified agenda tick — the core proactive agent loop.

    Replaces: fsrs_review_job, daily_suggestion_job, progress_driven_review_job,
    inactivity_alert_job, study_reminder_job.

    For each user, runs the agenda service which:
    1. Collects signals (goals, deadlines, forgetting risk, weak areas, inactivity)
    2. Ranks deterministically (no LLM)
    3. Deduplicates to avoid spam
    4. Materialises a single AgentTask if warranted
    5. Optionally notifies the user

    UPGRADED (Phase 1): After the deterministic tick, runs an LLM-enhanced
    Ambient Study Monitor (OpenClaw Heartbeat pattern) that can make richer
    decisions: trigger goal pursuit, generate reports, or craft personalised
    notifications.
    """
    from models.course import Course
    from services.agent.agenda import run_agenda_tick

    import time as _time

    _start = _time.monotonic()
    logger.info("Running agenda tick job...")
    ticks_run = 0
    tasks_created = 0
    ambient_actions = 0
    skipped_users = 0
    sem = asyncio.Semaphore(5)

    user_ids = await _get_user_ids()

    # D1 optimisation: skip users inactive for 7+ days
    active_user_ids: list[uuid.UUID] = []
    try:
        async with async_session() as _db:
            from sqlalchemy import text as sa_text
            from database import is_sqlite as _is_sq
            if _is_sq():
                _recent_q = "SELECT DISTINCT user_id FROM chat_messages WHERE created_at >= datetime('now', '-7 days')"
            else:
                _recent_q = "SELECT DISTINCT user_id FROM chat_messages WHERE created_at >= NOW() - INTERVAL '7 days'"
            rows = await _db.execute(sa_text(_recent_q))
            recent_active = {row[0] for row in rows.fetchall()}
            for uid in user_ids:
                if uid in recent_active:
                    active_user_ids.append(uid)
                else:
                    skipped_users += 1
    except (SQLAlchemyError, ImportError) as e:
        active_user_ids = list(user_ids)  # Fallback: process everyone
        logger.warning("Activity filter skipped (table may not exist): %s", e, exc_info=True)

    if skipped_users:
        logger.info("Agenda tick: skipping %d inactive users", skipped_users)

    async def _process_user(user_id: uuid.UUID) -> tuple[int, int, int]:
        """Process a single user's agenda ticks + ambient monitor."""
        u_ticks = 0
        u_tasks = 0
        u_ambient = 0

        async with sem, async_session() as db:
            course_result = await db.execute(
                select(Course.id).where(Course.user_id == user_id)
            )
            course_ids = [row[0] for row in course_result.all()]

            # Also run a cross-course tick (course_id=None) for inactivity, etc.
            tick_targets = [None] + course_ids

            for course_id in tick_targets:
                try:
                    run = await run_agenda_tick(
                        user_id=user_id,
                        course_id=course_id,
                        trigger="scheduler",
                        db=db,
                        notify=True,
                    )
                    u_ticks += 1
                    if run.status not in ("noop", "failed"):
                        u_tasks += 1
                except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
                    logger.exception(
                        "Agenda tick failed for user=%s course=%s",
                        user_id, course_id,
                    )

            # --- Ambient Study Monitor (LLM deliberation layer) ---
            if not settings.ambient_monitor_enabled:
                return u_ticks, u_tasks, u_ambient
            try:
                from services.agent.ambient_monitor import (
                    gather_learning_state,
                    llm_deliberate,
                    execute_ambient_decision,
                )
                from services.agent.agenda_signals import collect_signals

                all_signals = await collect_signals(user_id, course_id=None, db=db)
                state = await gather_learning_state(user_id, all_signals, db)
                decision = await llm_deliberate(state)

                if decision and decision.get("action") != "silent":
                    status = await execute_ambient_decision(user_id, decision, db)
                    u_ambient += 1
                    logger.info(
                        "Ambient monitor for user=%s: action=%s status=%s reason=%s",
                        user_id, decision.get("action"), status, decision.get("reason", ""),
                    )
            except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
                logger.exception("Ambient monitor skipped for user %s", user_id)

        return u_ticks, u_tasks, u_ambient

    results = await asyncio.gather(
        *[_process_user(uid) for uid in active_user_ids],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, tuple):
            ticks_run += r[0]
            tasks_created += r[1]
            ambient_actions += r[2]
        elif isinstance(r, Exception):
            logger.error("Agenda tick outer loop failed: %s", r)

    _elapsed = (_time.monotonic() - _start) * 1000
    logger.info(
        "Agenda tick complete: ticks=%d tasks_created=%d ambient_actions=%d "
        "active_users=%d skipped=%d elapsed=%.0fms",
        ticks_run, tasks_created, ambient_actions,
        len(active_user_ids), skipped_users, _elapsed,
    )


async def scrape_refresh_job():
    """Auto-scrape refresh job — re-scrape enabled URLs with change detection."""
    logger.info("Running auto-scrape refresh job...")
    try:
        from services.scraper.runner import run_scrape_refresh

        async with async_session() as db:
            result = await run_scrape_refresh(db)
            await db.commit()
            logger.info(
                "Scrape refresh: scraped=%d skipped=%d failed=%d",
                result["scraped"], result["skipped"], result["failed"],
            )
    except (SQLAlchemyError, ImportError, KeyError, OSError):
        logger.exception("Scrape refresh job failed")


async def memory_consolidation_job():
    """Memory consolidation job — dedup, decay, and categorize memories.

    Runs the MemoryConsolidationAgent pipeline (OpenClaw cron lane pattern):
    1. Deduplication (word overlap + same-type matching)
    2. Recency decay (type-aware half-life)
    3. Categorization (memU 3-layer pattern via LLM)

    Runs every 6 hours for all users.
    """
    logger.info("Running memory consolidation job...")
    user_ids = await _get_user_ids()

    total_deduped = 0
    total_decayed = 0
    total_categorized = 0

    for user_id in user_ids:
        try:
            async with async_session() as db:
                from services.agent.memory_agent import run_full_consolidation
                consolidation = await run_full_consolidation(db, user_id)
                total_deduped += consolidation.get("deduped", 0)
                total_decayed += consolidation.get("decayed", 0)
                total_categorized += consolidation.get("categorized", 0)

        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
            logger.exception("Memory consolidation failed for user %s", user_id)

    logger.info(
        "Memory consolidation complete: deduped=%d decayed=%d categorized=%d",
        total_deduped, total_decayed, total_categorized,
    )


# NOTE: The following jobs have been consolidated into agenda_tick_job:
# - inactivity_alert_job  → inactivity signal
# - daily_suggestion_job  → forgetting_risk signal
# - progress_driven_review_job → weak_area signal
# - study_reminder_job    → active_goal + deadline signals
# - fsrs_review_job       → forgetting_risk signal


async def timing_analysis_job():
    """Timing analysis — no-op stub (notification system removed in Phase 1.1)."""
    logger.debug("Timing analysis job skipped (notification system removed)")


async def escalation_check_job():
    """Escalation check — no-op stub (notification system removed in Phase 1.1)."""
    logger.debug("Escalation check job skipped (notification system removed)")
