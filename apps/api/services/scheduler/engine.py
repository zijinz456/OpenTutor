"""Scheduler engine — APScheduler-based proactive reminders + FSRS review push.

Runs as a background task inside the FastAPI lifespan.

Jobs:
1. weekly_prep_job — runs every Monday 8:00 AM, triggers WF-2 for all users
2. fsrs_review_job — runs every hour, checks for due flashcards and pushes reminders
3. scrape_refresh_job — runs every 24h, re-scrapes URLs with auto-scrape enabled
4. timing_analysis_job — runs daily, computes preferred study times from habit logs
5. escalation_check_job — runs every 2 hours, escalates unread high-priority notifications

Notifications are dispatched through NotificationDispatcher which handles dedup,
quiet hours, frequency caps, channel routing, and delivery tracking.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func

from database import async_session
from models.agent_task import AgentTask
from models.user import User
from models.progress import LearningProgress
from models.notification import Notification
from models.study_goal import StudyGoal
from services.notification.dispatcher import dispatch as dispatch_notification
from services.activity.engine import submit_task
from services.provenance import build_provenance

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# SSE subscriber management has moved to services.notification.channels.sse.
# Re-export for backward compatibility.
from services.notification.channels.sse import subscribe_sse, unsubscribe_sse  # noqa: F401


async def _push_notification(
    user_id: uuid.UUID,
    title: str,
    body: str,
    category: str = "reminder",
    course_id: uuid.UUID | None = None,
    priority: str = "normal",
    dedup_key: str | None = None,
):
    """Dispatch notification via NotificationDispatcher.

    Wraps the central dispatch() call with its own DB session, suitable for
    scheduler jobs that run outside a request context.
    """
    async with async_session() as db:
        await dispatch_notification(
            user_id=user_id,
            title=title,
            body=body,
            category=category,
            course_id=course_id,
            priority=priority,
            dedup_key=dedup_key,
            db=db,
        )


async def weekly_prep_job():
    """Weekly prep job — triggers WF-2 for all users every Monday."""
    logger.info("Running weekly prep job...")
    async with async_session() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()
        now = datetime.now(timezone.utc)
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)

        for user in users:
            try:
                goal = await _get_or_create_weekly_review_goal(db, user.id, week_start)
                if await _has_scheduled_weekly_task(db, user.id, goal.id, week_start):
                    continue
                await submit_task(
                    user_id=user.id,
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
                    user.id,
                    "Weekly Review Queued",
                    "OpenTutor queued your weekly review task. Approve or inspect it from the activity panel once it starts.",
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
                await _push_notification(
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


async def progress_driven_review_job():
    """Progress-driven review — auto-generate targeted review tasks for weak areas.

    This is the core "autonomous agent loop":
    1. Check each user's learning progress for topics with low mastery
    2. If unmastered wrong answers exceed a threshold, auto-create a review_drill task
    3. Notify the user so they can approve and begin the review

    This connects the FSRS data with the agent task system to make the agent
    proactively drive learning, not just respond to user messages.
    """
    logger.info("Running progress-driven review job...")
    from models.wrong_answer import WrongAnswer

    async with async_session() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()
        now = datetime.now(timezone.utc)
        tasks_created = 0

        for user in users:
            try:
                # Count unmastered wrong answers per course
                wa_result = await db.execute(
                    select(
                        WrongAnswer.course_id,
                        func.count(WrongAnswer.id).label("unmastered_count"),
                    )
                    .where(
                        WrongAnswer.user_id == user.id,
                        WrongAnswer.mastered.is_(False),
                    )
                    .group_by(WrongAnswer.course_id)
                )
                rows = wa_result.all()

                for row in rows:
                    course_id, unmastered_count = row
                    if unmastered_count < 3:
                        continue  # Not enough weak areas to warrant a task

                    # Check if we already created a review task today for this course
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    existing = await db.execute(
                        select(AgentTask).where(
                            AgentTask.user_id == user.id,
                            AgentTask.course_id == course_id,
                            AgentTask.task_type == "wrong_answer_review",
                            AgentTask.source == "scheduler",
                            AgentTask.created_at >= today_start,
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none():
                        continue  # Already created today

                    # Create the review task (requires approval)
                    await submit_task(
                        user_id=user.id,
                        task_type="wrong_answer_review",
                        title=f"Review {unmastered_count} weak areas",
                        summary=f"You have {unmastered_count} unmastered wrong answers. "
                                f"This task will generate targeted exercises to strengthen these areas.",
                        source="scheduler",
                        input_json={
                            "course_id": str(course_id),
                            "trigger": "progress_check",
                            "unmastered_count": unmastered_count,
                        },
                        metadata_json={
                            "provenance": build_provenance(
                                workflow="progress_driven_review",
                                generated=True,
                                source_labels=["workflow", "generated", "scheduler"],
                                scheduler_trigger="progress_check",
                            ),
                        },
                        max_attempts=2,
                        requires_approval=True,
                        course_id=course_id,
                    )
                    await _push_notification(
                        user.id,
                        f"{unmastered_count} weak areas detected",
                        "OpenTutor found topics you're struggling with and queued a targeted review. "
                        "Approve the task from the activity panel to start.",
                        category="progress_review",
                        course_id=course_id,
                    )
                    tasks_created += 1

            except Exception as e:
                logger.error("Progress-driven review failed for user %s: %s", user.id, e)

        logger.info("Progress-driven review complete: created %d tasks", tasks_created)


async def timing_analysis_job():
    """Timing analysis — compute preferred study times from habit logs.

    Uses services.notification.timing.compute_preferred_study_time() to
    analyse each user's study patterns and update their NotificationSettings
    with the learned preferred_study_time and confidence score.

    Runs once daily.
    """
    logger.info("Running timing analysis job...")
    from services.notification.timing import compute_preferred_study_time
    from services.notification.dispatcher import get_or_create_settings

    async with async_session() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        updated = 0
        for user in users:
            try:
                preferred_time, confidence = await compute_preferred_study_time(
                    user.id, db
                )
                if preferred_time is not None:
                    ns = await get_or_create_settings(user.id, db)
                    ns.preferred_study_time = preferred_time
                    ns.study_time_confidence = confidence
                    updated += 1
            except Exception as e:
                logger.error("Timing analysis failed for user %s: %s", user.id, e)

        await db.commit()
        logger.info("Timing analysis complete: updated %d/%d users", updated, len(users))


async def escalation_check_job():
    """Escalation check — re-deliver unread high-priority notifications.

    Finds notifications with priority "high" or "urgent" that have not been
    read within the user's configured escalation_delay_hours window, and
    re-dispatches them with "urgent" priority so the dispatcher bypasses
    quiet hours and frequency caps on the second delivery attempt.

    Runs every 2 hours.
    """
    logger.info("Running escalation check job...")
    from models.notification_settings import NotificationSettings

    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # Find users with escalation enabled
        settings_result = await db.execute(
            select(NotificationSettings).where(
                NotificationSettings.escalation_enabled.is_(True)
            )
        )
        all_settings = settings_result.scalars().all()

        escalated = 0
        for ns in all_settings:
            try:
                cutoff = now - timedelta(hours=ns.escalation_delay_hours)

                # Unread high-priority notifications older than the escalation window
                notif_result = await db.execute(
                    select(Notification).where(
                        Notification.user_id == ns.user_id,
                        Notification.read.is_(False),
                        Notification.priority.in_(["high", "urgent"]),
                        Notification.created_at <= cutoff,
                    )
                )
                unread = notif_result.scalars().all()

                for notif in unread:
                    # Mark original as read to prevent re-escalation loops
                    notif.read = True

                    await dispatch_notification(
                        user_id=ns.user_id,
                        title=f"[Reminder] {notif.title}",
                        body=notif.body,
                        category=notif.category,
                        course_id=notif.course_id,
                        priority="urgent",
                        dedup_key=f"escalation-{notif.id}",
                        db=db,
                    )
                    escalated += 1
            except Exception as e:
                logger.error("Escalation check failed for user %s: %s", ns.user_id, e)

        await db.commit()
        logger.info("Escalation check complete: escalated %d notifications", escalated)


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


async def study_reminder_job():
    """Study reminder job — check goals with target dates and send reminders.

    For each active goal approaching its target_date, send a notification
    reminding the student to work toward it. Deduplicates by goal ID + date.
    """
    logger.info("Running study reminder job...")
    now = _utcnow()
    reminded = 0

    async with async_session() as db:
        # Find active goals with target_date within the next 3 days
        result = await db.execute(
            select(StudyGoal).where(
                StudyGoal.status == "active",
                StudyGoal.target_date.isnot(None),
                StudyGoal.target_date <= now + timedelta(days=3),
                StudyGoal.target_date >= now - timedelta(hours=1),
            )
        )
        goals = result.scalars().all()

        for goal in goals:
            days_left = (goal.target_date - now).days
            if days_left < 0:
                urgency = "overdue"
                title = f"Goal overdue: {goal.title}"
                body = f'Your goal "{goal.title}" is past its target date. Consider updating or completing it.'
                priority = "high"
            elif days_left == 0:
                urgency = "today"
                title = f"Goal due today: {goal.title}"
                body = f'Your goal "{goal.title}" is due today! {goal.next_action or "Time to finish up."}'
                priority = "high"
            elif days_left == 1:
                urgency = "tomorrow"
                title = f"Goal due tomorrow: {goal.title}"
                body = f'Your goal "{goal.title}" is due tomorrow. {goal.next_action or "Keep going!"}'
                priority = "normal"
            else:
                urgency = "soon"
                title = f"Goal due in {days_left} days: {goal.title}"
                body = f'Your goal "{goal.title}" is coming up. {goal.next_action or "Stay on track!"}'
                priority = "normal"

            dedup_key = f"study_reminder:{goal.id}:{now.strftime('%Y-%m-%d')}:{urgency}"
            try:
                await _push_notification(
                    user_id=goal.user_id,
                    title=title,
                    body=body,
                    category="study_reminder",
                    course_id=goal.course_id,
                    priority=priority,
                    dedup_key=dedup_key,
                )
                reminded += 1
            except Exception as e:
                logger.warning("Failed to send study reminder for goal %s: %s", goal.id, e)

    logger.info("Study reminder job complete: %d reminders sent", reminded)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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

    # Timing analysis: daily at 3:00 AM (low-traffic window)
    scheduler.add_job(
        timing_analysis_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="timing_analysis",
        name="Study Timing Analysis",
        replace_existing=True,
    )

    # Progress-driven review: every 4 hours (core autonomous agent loop)
    scheduler.add_job(
        progress_driven_review_job,
        trigger=IntervalTrigger(hours=4),
        id="progress_driven_review",
        name="Progress-Driven Review (auto-generate tasks for weak areas)",
        replace_existing=True,
    )

    # Escalation check: every 2 hours
    scheduler.add_job(
        escalation_check_job,
        trigger=IntervalTrigger(hours=2),
        id="escalation_check",
        name="Notification Escalation Check",
        replace_existing=True,
    )

    # Study goal reminders: every 4 hours
    scheduler.add_job(
        study_reminder_job,
        trigger=IntervalTrigger(hours=4),
        id="study_reminder",
        name="Study Goal Reminder (target date alerts)",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))


def stop_scheduler():
    """Gracefully stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
