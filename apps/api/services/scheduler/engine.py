"""Scheduler engine — APScheduler-based proactive agent loop + maintenance jobs.

Runs as a background task inside the FastAPI lifespan.

Core loop:
- agenda_tick_job — runs every 2 hours, executes the unified agenda tick per user
  (replaces the old fsrs_review, daily_suggestion, progress_driven_review,
   inactivity_alert, and study_reminder jobs)

Standalone maintenance jobs:
- weekly_prep_job    — every Monday 8:00 AM
- scrape_refresh_job — every hour
- memory_consolidation_job — every 6 hours
- timing_analysis_job      — daily 3:00 AM
- escalation_check_job     — every 2 hours
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from config import settings
from database import async_session
from models.agent_task import AgentTask
from models.study_goal import StudyGoal
from models.user import User
from services.activity.engine import submit_task
from services.provenance import build_provenance

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


# No-op stubs for removed SSE subscriber management (backward compatibility).
async def subscribe_sse(*a, **kw):
    pass

async def unsubscribe_sse(*a, **kw):
    pass


async def _get_user_ids() -> list[uuid.UUID]:
    """Fetch all user IDs in a short-lived session.

    Used by scheduler jobs so each user can be processed in its own
    isolated session — preventing one user's DB error from corrupting
    the session state for subsequent users.
    """
    async with async_session() as db:
        result = await db.execute(select(User.id))
        return [row[0] for row in result.all()]


async def _for_each_user(processor, label: str) -> int:
    """Run a processor callback for every user, each in its own DB session.

    ``processor(user_id, db)`` should return a truthy value when the
    operation counted as successful.  Exceptions are logged and
    do not abort the loop.

    Returns the count of successful invocations.
    """
    user_ids = await _get_user_ids()
    count = 0
    for user_id in user_ids:
        try:
            async with async_session() as db:
                result = await processor(user_id, db)
                if result:
                    count += 1
        except Exception as e:
            logger.error("%s failed for user %s: %s", label, user_id, e)
    return count


async def _push_notification(
    user_id: uuid.UUID,
    title: str,
    body: str,
    category: str = "reminder",
    **kwargs,
):
    """Store an in-app notification for the user."""
    try:
        from models.notification import Notification

        async with async_session() as db:
            notif = Notification(
                user_id=user_id,
                title=title,
                body=body,
                category=category,
                metadata_json=kwargs.get("data"),
            )
            db.add(notif)
            await db.commit()
            logger.debug("Notification stored: [%s] %s for user %s", category, title, user_id)
    except Exception as e:
        logger.error("Failed to store notification for user %s: %s", user_id, e)


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
        except Exception as e:
            logger.error("Weekly prep failed for user %s: %s", user_id, e)


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
    except Exception:
        active_user_ids = list(user_ids)  # Fallback: process everyone
        logger.debug("Activity filter skipped (table may not exist)")

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
                except Exception as e:
                    logger.error(
                        "Agenda tick failed for user=%s course=%s: %s",
                        user_id, course_id, e,
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
            except Exception as e:
                logger.debug("Ambient monitor skipped for user %s: %s", user_id, e)

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
    except Exception as e:
        logger.error("Scrape refresh job failed: %s", e)


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

        except Exception as e:
            logger.error("Memory consolidation failed for user %s: %s", user_id, e)

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


async def _broadcast_report_job(
    name: str,
    generator_module: str,
    generator_func_name: str,
    title: str,
    category: str,
    dedup_pattern: str,
    action_label: str,
):
    """Shared helper for broadcast report jobs (daily brief, weekly report, etc.).

    Fetches all users, generates a report per user via the given generator
    function, and dispatches a notification with the result.
    """
    import importlib

    logger.info("Running %s job...", name)
    module = importlib.import_module(generator_module)
    generator = getattr(module, generator_func_name)

    user_ids = await _get_user_ids()
    sem = asyncio.Semaphore(5)
    sent = 0

    async def _send(user_id: uuid.UUID) -> bool:
        async with sem, async_session() as db:
            content = await generator(user_id, db)
            if content:
                logger.debug("Report generated for user %s [%s]: %s", user_id, category, content[:100])
                return True
            return False

    results = await asyncio.gather(
        *[_send(uid) for uid in user_ids],
        return_exceptions=True,
    )
    for r in results:
        if r is True:
            sent += 1
        elif isinstance(r, Exception):
            logger.error("%s failed: %s", name, r)

    logger.info("%s complete: sent to %d users", name, sent)


async def daily_brief_job():
    """Daily learning brief — personalised morning summary.

    Generates a short report and sends it as a notification.
    Runs every morning at 8:00 AM.
    """
    await _broadcast_report_job(
        name="Daily brief",
        generator_module="services.report.generator",
        generator_func_name="generate_daily_brief",
        title="Good morning — your daily learning brief",
        category="daily_brief",
        dedup_pattern="%Y-%m-%d",
        action_label="View Dashboard",
    )


async def weekly_report_job():
    """Weekly learning report — comprehensive summary of the past week.

    Runs every Sunday at 8:00 PM.
    """
    await _broadcast_report_job(
        name="Weekly report",
        generator_module="services.report.generator",
        generator_func_name="generate_weekly_report",
        title="Your weekly learning summary",
        category="weekly_report",
        dedup_pattern="%Y-%W",
        action_label="View Details",
    )


async def smart_review_trigger_job():
    """Smart review session trigger — Orbit-style forgetting cost batching.

    Instead of naively notifying on every due card, estimates the expected
    forgetting cost and only triggers when it's worthwhile.
    """
    logger.info("Running smart review trigger job...")
    from models.progress import LearningProgress
    from services.spaced_repetition.fsrs import FSRSCard, estimate_session_urgency

    async def _process(user_id, db):
        now = datetime.now(timezone.utc)
        items_result = await db.execute(
            select(LearningProgress)
            .where(
                LearningProgress.user_id == user_id,
                LearningProgress.next_review_at.isnot(None),
                LearningProgress.next_review_at <= now,
                LearningProgress.mastery_score < 0.9,
            )
            .order_by(LearningProgress.next_review_at.asc())
            .limit(50)
        )
        items = items_result.scalars().all()
        if not items:
            return False

        # Convert to FSRSCard for cost estimation
        cards = []
        for item in items:
            due_at = item.next_review_at
            if due_at and due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            stability = float(item.fsrs_stability) if item.fsrs_stability and item.fsrs_stability > 0 else 1.0
            cards.append(FSRSCard(stability=stability, due=due_at))

        assessment = estimate_session_urgency(cards, now)

        if assessment["urgency"] not in ("high", "critical"):
            return False

        # Skip if a review_session is already queued/running for this user
        active_review = await db.execute(
            select(AgentTask.id)
            .where(
                AgentTask.user_id == user_id,
                AgentTask.task_type == "review_session",
                AgentTask.status.in_(("queued", "running", "pending_approval")),
            )
            .limit(1)
        )
        if active_review.scalar_one_or_none() is not None:
            return False

        await submit_task(
            user_id=user_id,
            task_type="review_session",
            title=f"Review {assessment['due_count']} at-risk items",
            summary=assessment["recommendation"],
            source="smart_review_trigger",
            input_json={
                "session_kind": "due_review",
                "trigger_signal": "forgetting_cost",
                "forgetting_cost": assessment["forgetting_cost"],
            },
            requires_approval=False,
            max_attempts=2,
        )
        logger.debug("Smart review task queued for user %s", user_id)
        return True

    triggered = await _for_each_user(_process, "Smart review trigger")
    logger.info("Smart review trigger complete: triggered for %d users", triggered)


async def bkt_training_job():
    """Weekly job: retrain BKT parameters per user."""
    logger.info("Running BKT training job...")
    user_ids = await _get_user_ids()
    trained_bkt = 0

    for user_id in user_ids:
        try:
            async with async_session() as db:
                from models.course import Course
                course_result = await db.execute(
                    select(Course.id).where(Course.user_id == user_id)
                )
                course_ids = [row[0] for row in course_result.all()]

                for course_id in course_ids:
                    try:
                        from services.learning_science.bkt_trainer import train_bkt_params
                        fitted = await train_bkt_params(db, user_id, course_id)
                        if fitted:
                            trained_bkt += 1
                    except Exception as e:
                        logger.debug("BKT training skipped for user=%s course=%s: %s", user_id, course_id, e)

        except Exception as e:
            logger.error("BKT training failed for user %s: %s", user_id, e)

    logger.info("BKT training complete: bkt_fitted=%d", trained_bkt)


async def cross_course_linking_job():
    """Periodic job: discover shared concepts across courses and store for teaching agent.

    Phase 4: Cross-course knowledge transfer.
    """
    logger.info("Running cross-course linking job...")
    user_ids = await _get_user_ids()
    links_found = 0

    for user_id in user_ids:
        try:
            async with async_session() as db:
                from models.course import Course
                from models.progress import LearningProgress

                course_result = await db.execute(
                    select(Course.id, Course.name).where(Course.user_id == user_id)
                )
                courses = course_result.all()
                if len(courses) < 2:
                    continue

                # Collect knowledge points per course with mastery
                course_concepts: dict[str, list[dict]] = {}
                for course_id, course_name in courses:
                    progress_result = await db.execute(
                        select(LearningProgress).where(
                            LearningProgress.user_id == user_id,
                            LearningProgress.course_id == course_id,
                        )
                    )
                    for lp in progress_result.scalars().all():
                        label = (lp.content_node_title or "").lower().strip()
                        if not label or len(label) < 3:
                            continue
                        course_concepts.setdefault(label, []).append({
                            "course_id": str(course_id),
                            "course_name": course_name,
                            "mastery": round(lp.mastery_score, 3),
                        })

                # Find concepts appearing in 2+ courses
                shared = {
                    k: v for k, v in course_concepts.items()
                    if len(v) >= 2 and len({c["course_id"] for c in v}) >= 2
                }

                if shared:
                    patterns = [
                        {"topic": topic, "courses": appearances}
                        for topic, appearances in list(shared.items())[:10]
                    ]

                    # Store for context_builder to pick up
                    from services.agent.kv_store import kv_set
                    await kv_set(
                        db, user_id, "cross_course", "patterns",
                        {"patterns": patterns, "updated_at": datetime.now(timezone.utc).isoformat()},
                        course_id=None,
                    )

                    # Auto-generate review tasks for large mastery gaps
                    for pattern in patterns:
                        masteries = [c["mastery"] for c in pattern["courses"]]
                        gap = max(masteries) - min(masteries)
                        if gap < 0.3:
                            continue

                        # Find the weak course (lowest mastery)
                        weak = min(pattern["courses"], key=lambda c: c["mastery"])
                        strong = max(pattern["courses"], key=lambda c: c["mastery"])
                        weak_course_id = uuid.UUID(weak["course_id"])

                        # Skip if a cross_course_review task already exists
                        existing = await db.execute(
                            select(AgentTask.id)
                            .where(
                                AgentTask.user_id == user_id,
                                AgentTask.task_type == "cross_course_review",
                                AgentTask.status.in_(("queued", "running", "pending_approval")),
                            )
                            .limit(1)
                        )
                        if existing.scalar_one_or_none() is not None:
                            continue

                        await submit_task(
                            user_id=user_id,
                            task_type="cross_course_review",
                            title=f"Review '{pattern['topic']}' for {weak['course_name']}",
                            summary=(
                                f"You've mastered '{pattern['topic']}' in {strong['course_name']} "
                                f"({strong['mastery']:.0%}) but it's weaker in "
                                f"{weak['course_name']} ({weak['mastery']:.0%}). "
                                f"A focused review can help transfer your knowledge."
                            ),
                            source="cross_course_linking",
                            input_json={
                                "topic": pattern["topic"],
                                "strong_course": strong,
                                "weak_course": weak,
                                "mastery_gap": round(gap, 3),
                            },
                            requires_approval=False,
                            max_attempts=2,
                        )
                        logger.debug("Cross-course review task queued for user %s: %s", user_id, pattern["topic"])

                    await db.commit()
                    links_found += len(patterns)

        except Exception as e:
            logger.debug("Cross-course linking failed for user %s: %s", user_id, e)

    logger.info("Cross-course linking complete: links_found=%d", links_found)


async def heartbeat_review_job():
    """Heartbeat — LECTOR-powered proactive review reminders.

    Checks each user's courses for concepts at risk of being forgotten.
    Uses LECTOR's semantic review summary (prerequisite decay, confusion pairs,
    stability-based forgetting) to create targeted review notifications.

    Runs every 6 hours.
    """
    logger.info("Running heartbeat review job...")
    from models.course import Course
    from services.lector import get_review_summary

    notified = 0

    async def _check_user(user_id, db):
        course_result = await db.execute(
            select(Course.id, Course.name).where(Course.user_id == user_id)
        )
        courses = course_result.all()
        user_notified = False

        for course_id, course_name in courses:
            try:
                summary = await get_review_summary(db, user_id, course_id)
                if not summary["needs_review"] or summary["urgent_count"] < 2:
                    continue

                await _push_notification(
                    user_id,
                    title=f"Review needed: {course_name}",
                    body=summary["recommendation"],
                    category="review_reminder",
                    data={
                        "course_id": str(course_id),
                        "urgent_count": summary["urgent_count"],
                        "concepts_at_risk": summary["concepts_at_risk"],
                    },
                )
                user_notified = True
            except Exception as e:
                logger.debug("Heartbeat check failed for course %s: %s", course_id, e)

        return user_notified

    notified = await _for_each_user(_check_user, "Heartbeat review")
    logger.info("Heartbeat review complete: notified %d users", notified)


_SCHEDULED_JOBS: list[tuple] = [
    # (func, trigger, job_id, name)
    # Core agent loop
    (agenda_tick_job, IntervalTrigger(hours=2), "agenda_tick", "Agenda Tick (unified proactive agent loop)"),
    # Standalone maintenance jobs
    (weekly_prep_job, CronTrigger(day_of_week="mon", hour=8, minute=0), "weekly_prep", "Weekly Study Prep (WF-2)"),
    (scrape_refresh_job, IntervalTrigger(hours=1), "scrape_refresh", "Auto-Scrape Refresh"),
    (memory_consolidation_job, IntervalTrigger(hours=6), "memory_consolidation", "Memory Consolidation (dedup + decay + categorize)"),
    (timing_analysis_job, CronTrigger(hour=3, minute=0), "timing_analysis", "Study Timing Analysis"),
    (escalation_check_job, IntervalTrigger(hours=2), "escalation_check", "Notification Escalation Check"),
    # Phase 1: Proactive agent jobs
    (daily_brief_job, CronTrigger(hour=8, minute=0), "daily_brief", "Daily Learning Brief"),
    (weekly_report_job, CronTrigger(day_of_week="sun", hour=20, minute=0), "weekly_report", "Weekly Learning Report"),
    (smart_review_trigger_job, IntervalTrigger(hours=4), "smart_review_trigger", "Smart Review Trigger (forgetting cost)"),
    # Phase 4: Training + linking
    (bkt_training_job, CronTrigger(day_of_week="sat", hour=3, minute=0), "bkt_training", "BKT Training"),
    (cross_course_linking_job, IntervalTrigger(hours=12), "cross_course_linking", "Cross-Course Knowledge Linking"),
    # Phase 2: Heartbeat — LECTOR-powered review reminders
    (heartbeat_review_job, IntervalTrigger(hours=6), "heartbeat_review", "Heartbeat Review (LECTOR semantic reminders)"),
]


def start_scheduler():
    """Start the APScheduler with all configured jobs."""
    for func, trigger, job_id, name in _SCHEDULED_JOBS:
        scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name,
            replace_existing=True,
        )

    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
