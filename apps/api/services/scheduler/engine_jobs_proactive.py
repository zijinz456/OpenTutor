"""Scheduler proactive jobs — reports, training, and linking.

Proactive review tasks are produced only by the agenda tick
(services.agent.agenda); nothing here submits review_session tasks.

Jobs:
- daily_brief_job           — daily morning summary (8:00 AM)
- weekly_report_job         — weekly learning report (Sunday 8:00 PM)
- bkt_training_job          — BKT parameter retraining (Saturday 3:00 AM)
- cross_course_linking_job  — cross-course knowledge transfer (every 12 hours)
"""

import asyncio
import importlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database import async_session
from services.scheduler.engine_helpers import (
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
    """Periodic job: discover shared concepts across a user's courses (LOOM only).

    Links same-name knowledge nodes across the user's courses with
    ``reinforces`` edges and stores the per-course mastery of each shared
    concept in the agent KV store (``cross_course/patterns``) for the
    context builder.  No-op unless ENABLE_EXPERIMENTAL_LOOM is on.
    """
    from services.loom_flags import loom_enabled

    if not loom_enabled():
        logger.debug("Cross-course linking skipped (LOOM disabled)")
        return

    logger.info("Running cross-course linking job...")
    user_ids = await _get_user_ids()
    links_found = 0

    for user_id in user_ids:
        try:
            async with async_session() as db:
                from models.course import Course
                from models.knowledge_graph import ConceptMastery, KnowledgeNode
                from services.loom_graph import link_cross_course_concepts

                course_result = await db.execute(
                    select(Course.id, Course.name).where(Course.user_id == user_id)
                )
                courses = course_result.all()
                if len(courses) < 2:
                    continue
                course_names = {cid: name for cid, name in courses}

                for course_id in course_names:
                    await link_cross_course_concepts(db, course_id)

                rows = await db.execute(
                    select(KnowledgeNode.name, KnowledgeNode.course_id, ConceptMastery.mastery_score)
                    .outerjoin(
                        ConceptMastery,
                        (ConceptMastery.knowledge_node_id == KnowledgeNode.id)
                        & (ConceptMastery.user_id == user_id),
                    )
                    .where(KnowledgeNode.course_id.in_(list(course_names)))
                )
                course_concepts: dict[str, list[dict]] = {}
                for name, course_id, mastery in rows.all():
                    label = (name or "").lower().strip()
                    if len(label) < 3:
                        continue
                    course_concepts.setdefault(label, []).append({
                        "course_id": str(course_id),
                        "course_name": course_names.get(course_id, ""),
                        "mastery": round(float(mastery or 0.0), 3),
                    })

                shared = {
                    k: v for k, v in course_concepts.items()
                    if len({c["course_id"] for c in v}) >= 2
                }
                if shared:
                    patterns = [
                        {"topic": topic, "courses": appearances}
                        for topic, appearances in list(shared.items())[:10]
                    ]
                    from services.agent.kv_store import kv_set
                    await kv_set(
                        db, user_id, "cross_course", "patterns",
                        {"patterns": patterns, "updated_at": datetime.now(timezone.utc).isoformat()},
                        course_id=None,
                    )
                    links_found += len(patterns)
                await db.commit()

        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError, SQLAlchemyError):
            logger.exception("Cross-course linking failed for user %s", user_id)

    logger.info("Cross-course linking complete: links_found=%d", links_found)
