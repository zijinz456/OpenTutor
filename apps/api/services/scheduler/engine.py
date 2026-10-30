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
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from services.scheduler.engine_jobs_maintenance import (
    agenda_tick_job,
    canvas_session_keepalive_job,
    memory_consolidation_job,
    scrape_refresh_job,
    weekly_prep_job,
)
from services.scheduler.engine_jobs_proactive import (
    bkt_training_job,
    cross_course_linking_job,
    daily_brief_job,
    heartbeat_review_job,
    smart_review_trigger_job,
    weekly_report_job,
)

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

_SCHEDULED_JOBS: list[tuple] = [
    # (func, trigger, job_id, name)
    # Core agent loop
    (agenda_tick_job, IntervalTrigger(hours=2), "agenda_tick", "Agenda Tick (unified proactive agent loop)"),
    # Standalone maintenance jobs
    (weekly_prep_job, CronTrigger(day_of_week="mon", hour=8, minute=0), "weekly_prep", "Weekly Study Prep (WF-2)"),
    (scrape_refresh_job, IntervalTrigger(hours=1), "scrape_refresh", "Auto-Scrape Refresh"),
    (canvas_session_keepalive_job, IntervalTrigger(minutes=20), "canvas_keepalive", "Canvas Session Keep-Alive"),
    (memory_consolidation_job, IntervalTrigger(hours=6), "memory_consolidation", "Memory Consolidation (dedup + decay + categorize)"),
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
