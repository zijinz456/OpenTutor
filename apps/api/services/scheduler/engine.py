"""Scheduler engine — APScheduler-based proactive reminders + FSRS review push.

Runs as a background task inside the FastAPI lifespan.

Jobs:
1. weekly_prep_job — runs every Monday 8:00 AM, triggers WF-2 for all users
2. fsrs_review_job — runs every hour, checks for due flashcards and pushes reminders
3. scrape_refresh_job — runs every 24h, re-scrapes URLs with auto-scrape enabled

Notifications are stored in a `notifications` table and delivered via SSE or polling.
"""

import logging
import uuid
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func

from database import async_session
from models.user import User
from models.progress import LearningProgress
from models.course import Course

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# In-memory notification store (replace with DB table in production)
_notifications: list[dict] = []


def get_notifications(user_id: uuid.UUID | None = None, unread_only: bool = True) -> list[dict]:
    """Get pending notifications, optionally filtered by user."""
    results = _notifications
    if user_id:
        results = [n for n in results if n.get("user_id") == str(user_id)]
    if unread_only:
        results = [n for n in results if not n.get("read")]
    return results


def mark_notification_read(notification_id: str) -> bool:
    for n in _notifications:
        if n["id"] == notification_id:
            n["read"] = True
            return True
    return False


def _push_notification(user_id: uuid.UUID, title: str, body: str, category: str = "reminder"):
    notif = {
        "id": str(uuid.uuid4()),
        "user_id": str(user_id),
        "title": title,
        "body": body,
        "category": category,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read": False,
    }
    _notifications.append(notif)
    # Keep only last 200 notifications in memory
    if len(_notifications) > 200:
        _notifications.pop(0)
    logger.info("Notification pushed: [%s] %s — %s", category, title, body[:80])


async def weekly_prep_job():
    """Weekly prep job — triggers WF-2 for all users every Monday."""
    logger.info("Running weekly prep job...")
    async with async_session() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            try:
                from services.workflow.weekly_prep import run_weekly_prep
                plan_result = await run_weekly_prep(db, user.id)
                _push_notification(
                    user.id,
                    "Weekly Study Plan Ready",
                    f"Your plan for this week is ready. {len(plan_result.get('deadlines', []))} upcoming deadlines.",
                    category="weekly_prep",
                )
            except Exception as e:
                logger.error("Weekly prep failed for user %s: %s", user.id, e)


async def fsrs_review_job():
    """FSRS review job — checks for due flashcards and pushes reminders."""
    logger.info("Checking for due FSRS reviews...")
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # Find all progress entries where next_review_at <= now
        result = await db.execute(
            select(
                LearningProgress.user_id,
                func.count(LearningProgress.id).label("due_count"),
            )
            .where(
                LearningProgress.next_review_at.isnot(None),
                LearningProgress.next_review_at <= now,
                LearningProgress.mastery_level < 0.9,
            )
            .group_by(LearningProgress.user_id)
        )
        rows = result.all()

        for row in rows:
            user_id, due_count = row
            if due_count > 0:
                _push_notification(
                    user_id,
                    f"{due_count} Cards Due for Review",
                    f"You have {due_count} flashcards ready for spaced repetition review. Review now to strengthen your memory!",
                    category="fsrs_review",
                )


async def scrape_refresh_job():
    """Auto-scrape refresh job — placeholder for re-scraping URLs."""
    logger.info("Running auto-scrape refresh job...")
    # TODO: iterate courses with auto-scrape enabled, re-trigger URL scraping
    # For now just log
    async with async_session() as db:
        result = await db.execute(select(func.count(Course.id)))
        count = result.scalar()
        logger.info("Auto-scrape check: %d courses in system", count)


def start_scheduler():
    """Start the APScheduler with all configured jobs."""
    # Weekly prep: every Monday at 8:00 AM
    scheduler.add_job(
        weekly_prep_job,
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_prep",
        name="Weekly Study Prep (WF-2)",
        replace_existing=True,
    )

    # FSRS review check: every hour
    scheduler.add_job(
        fsrs_review_job,
        trigger=IntervalTrigger(hours=1),
        id="fsrs_review",
        name="FSRS Review Reminder",
        replace_existing=True,
    )

    # Auto-scrape refresh: every 24 hours
    scheduler.add_job(
        scrape_refresh_job,
        trigger=IntervalTrigger(hours=24),
        id="scrape_refresh",
        name="Auto-Scrape Refresh",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
