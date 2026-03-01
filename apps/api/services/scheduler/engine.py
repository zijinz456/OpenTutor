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
from models.notification import Notification

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# SSE subscribers: user_id → list of asyncio.Queue
_sse_subscribers: dict[str, list] = {}


def subscribe_sse(user_id: uuid.UUID):
    """Create an SSE subscription queue for a user."""
    import asyncio
    queue: asyncio.Queue = asyncio.Queue()
    key = str(user_id)
    _sse_subscribers.setdefault(key, []).append(queue)
    return queue


def unsubscribe_sse(user_id: uuid.UUID, queue):
    """Remove an SSE subscription."""
    key = str(user_id)
    subs = _sse_subscribers.get(key, [])
    if queue in subs:
        subs.remove(queue)


async def _push_notification(user_id: uuid.UUID, title: str, body: str, category: str = "reminder", course_id: uuid.UUID | None = None):
    """Persist notification to DB and push to SSE subscribers."""
    async with async_session() as db:
        notif = Notification(
            user_id=user_id,
            course_id=course_id,
            title=title,
            body=body,
            category=category,
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)

    logger.info("Notification pushed: [%s] %s — %s", category, title, body[:80])

    # Push to SSE subscribers
    import json
    payload = json.dumps({
        "id": str(notif.id),
        "title": title,
        "body": body,
        "category": category,
        "created_at": notif.created_at.isoformat() if notif.created_at else None,
    })
    key = str(user_id)
    for queue in _sse_subscribers.get(key, []):
        try:
            queue.put_nowait(payload)
        except Exception:
            pass


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
                LearningProgress.mastery_score < 0.9,
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
    async with async_session() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        total_deduped = 0
        total_decayed = 0
        total_categorized = 0

        for user in users:
            try:
                from services.agent.memory_agent import run_full_consolidation
                result = await run_full_consolidation(db, user.id)
                total_deduped += result.get("deduped", 0)
                total_decayed += result.get("decayed", 0)
                total_categorized += result.get("categorized", 0)
            except Exception as e:
                logger.error("Memory consolidation failed for user %s: %s", user.id, e)

        logger.info(
            "Memory consolidation complete: deduped=%d decayed=%d categorized=%d",
            total_deduped, total_decayed, total_categorized,
        )


async def inactivity_alert_job():
    """Inactivity alert — remind users who haven't studied for 3+ days."""
    logger.info("Checking for inactive users...")
    from datetime import timedelta
    threshold = datetime.now(timezone.utc) - timedelta(days=3)

    async with async_session() as db:
        from models.ingestion import StudySession
        # Find users whose most recent study session is older than threshold
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            session_result = await db.execute(
                select(StudySession)
                .where(StudySession.user_id == user.id)
                .order_by(StudySession.started_at.desc())
                .limit(1)
            )
            last_session = session_result.scalar_one_or_none()
            if last_session and last_session.started_at and last_session.started_at < threshold:
                days_inactive = (datetime.now(timezone.utc) - last_session.started_at).days
                await _push_notification(
                    user.id,
                    "We miss you!",
                    f"It's been {days_inactive} days since your last study session. "
                    f"Even 10 minutes of review can help retain what you've learned!",
                    category="inactivity",
                )


async def daily_suggestion_job():
    """Daily suggestion — push personalised study recommendation based on forgetting curve."""
    logger.info("Running daily suggestion job...")
    async with async_session() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()
        now = datetime.now(timezone.utc)

        for user in users:
            try:
                # Find knowledge points with lowest retrievability
                urgent = await db.execute(
                    select(LearningProgress)
                    .where(
                        LearningProgress.user_id == user.id,
                        LearningProgress.fsrs_reps > 0,
                        LearningProgress.next_review_at <= now,
                    )
                    .order_by(LearningProgress.next_review_at.asc())
                    .limit(5)
                )
                due_items = urgent.scalars().all()
                if due_items:
                    await _push_notification(
                        user.id,
                        f"{len(due_items)} topics need review today",
                        "Your spaced repetition schedule suggests reviewing these topics "
                        "before they fade from memory. Start a quick review session!",
                        category="fsrs_review",
                    )
            except Exception as e:
                logger.error("Daily suggestion failed for user %s: %s", user.id, e)


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

    # Auto-scrape refresh: check every hour, each source controls its own interval
    scheduler.add_job(
        scrape_refresh_job,
        trigger=IntervalTrigger(hours=1),
        id="scrape_refresh",
        name="Auto-Scrape Refresh",
        replace_existing=True,
    )

    # Memory consolidation: every 6 hours (OpenClaw cron lane pattern)
    scheduler.add_job(
        memory_consolidation_job,
        trigger=IntervalTrigger(hours=6),
        id="memory_consolidation",
        name="Memory Consolidation (dedup + decay + categorize)",
        replace_existing=True,
    )

    # Inactivity alert: daily at 10:00 AM
    scheduler.add_job(
        inactivity_alert_job,
        trigger=CronTrigger(hour=10, minute=0),
        id="inactivity_alert",
        name="Inactivity Alert (3+ days)",
        replace_existing=True,
    )

    # Daily suggestion: every day at 9:00 AM
    scheduler.add_job(
        daily_suggestion_job,
        trigger=CronTrigger(hour=9, minute=0),
        id="daily_suggestion",
        name="Daily Forgetting-Curve Suggestion",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
