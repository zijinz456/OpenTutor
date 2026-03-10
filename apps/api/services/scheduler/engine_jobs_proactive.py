"""Scheduler proactive jobs — reports, smart review, training, and linking.

Jobs:
- daily_brief_job           — daily morning summary (8:00 AM)
- weekly_report_job         — weekly learning report (Sunday 8:00 PM)
- smart_review_trigger_job  — forgetting cost batching (every 4 hours)
- bkt_training_job          — BKT parameter retraining (Saturday 3:00 AM)
- cross_course_linking_job  — cross-course knowledge transfer (every 12 hours)
- heartbeat_review_job      — LECTOR-powered review reminders (every 6 hours)
"""

import asyncio
import importlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database import async_session
from models.agent_task import AgentTask
from services.activity.engine import submit_task
from services.scheduler.engine_helpers import (
    _for_each_user,
    _get_user_ids,
    _push_notification,
)

logger = logging.getLogger(__name__)


# ── Broadcast report helper ──────────────────────────────────────────


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
    logger.info("Running %s job...", name)
    module = importlib.import_module(generator_module)
    generator = getattr(module, generator_func_name)

    user_ids = await _get_user_ids()
    sem = asyncio.Semaphore(5)
    sent = 0
    dedup_bucket = datetime.now(timezone.utc).strftime(dedup_pattern)
    dedup_key = f"{category}:{dedup_bucket}"

    async def _send(user_id: uuid.UUID) -> bool:
        async with sem, async_session() as db:
            content = await generator(user_id, db)
            if content:
                action_url = "/analytics" if category == "weekly_report" else "/"
                stored = await _push_notification(
                    user_id=user_id,
                    title=title,
                    body=content,
                    category=category,
                    dedup_key=dedup_key,
                    action_label=action_label,
                    action_url=action_url,
                    data={
                        "report_category": category,
                        "report_name": name,
                        "dedup_bucket": dedup_bucket,
                    },
                )
                if stored:
                    logger.debug(
                        "Report generated and notified for user %s [%s]: %s",
                        user_id,
                        category,
                        content[:100],
                    )
                return stored
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


# ── Jobs ─────────────────────────────────────────────────────────────


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
                    except (ValueError, TypeError, SQLAlchemyError, ImportError) as e:
                        logger.warning("BKT training skipped for user=%s course=%s: %s", user_id, course_id, e)

        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
            logger.exception("BKT training failed for user %s", user_id)

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

        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
            logger.exception("Cross-course linking failed for user %s", user_id)

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
            except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as e:
                logger.exception("Heartbeat check failed for course %s", course_id)

        return user_notified

    notified = await _for_each_user(_check_user, "Heartbeat review")
    logger.info("Heartbeat review complete: notified %d users", notified)
