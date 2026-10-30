"""Scheduler maintenance jobs — core agent loop and infrastructure tasks.

Jobs:
- agenda_tick_job       — unified proactive agent loop (every 2 hours)
- scrape_refresh_job    — auto-scrape refresh (every hour)
- memory_consolidation_job — dedup/decay/categorize (every 6 hours)
- canvas_session_keepalive_job — keep Canvas sessions alive (every 20 minutes)
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database import async_session
from services.scheduler.engine_helpers import _get_user_ids

logger = logging.getLogger(__name__)


# ── Jobs ─────────────────────────────────────────────────────────────


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

    This is the single producer of proactive review_session tasks.
    """
    from models.course import Course
    from services.agent.agenda import run_agenda_tick

    import time as _time

    _start = _time.monotonic()
    logger.info("Running agenda tick job...")
    ticks_run = 0
    tasks_created = 0
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

    async def _process_user(user_id: uuid.UUID) -> tuple[int, int]:
        """Process a single user's agenda ticks."""
        u_ticks = 0
        u_tasks = 0

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

        return u_ticks, u_tasks

    results = await asyncio.gather(
        *[_process_user(uid) for uid in active_user_ids],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, tuple):
            ticks_run += r[0]
            tasks_created += r[1]
        elif isinstance(r, Exception):
            logger.error("Agenda tick outer loop failed: %s", r)

    _elapsed = (_time.monotonic() - _start) * 1000
    logger.info(
        "Agenda tick complete: ticks=%d tasks_created=%d "
        "active_users=%d skipped=%d elapsed=%.0fms",
        ticks_run, tasks_created,
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


async def canvas_session_keepalive_job():
    """Keep Canvas sessions alive by periodically visiting the check URL.

    Canvas sessions expire after ~30 minutes of inactivity.  This job runs
    every 20 minutes and makes a lightweight HTTP request with the saved
    session cookies, which causes the Canvas server to reset the cookie
    expiry (Set-Cookie headers with renewed max-age).

    If a session is found to have expired (401 / redirect to login), it is
    marked invalid so the user knows to re-authenticate.
    """
    import json

    import httpx
    from sqlalchemy import select

    from models.scrape import AuthSession
    from services.browser.session_manager import SessionManager, _encrypt_data

    logger.info("Running Canvas session keep-alive job...")
    kept_alive = 0
    expired = 0
    skipped = 0

    try:
        async with async_session() as db:
            result = await db.execute(
                select(AuthSession).where(
                    AuthSession.is_valid.is_(True),
                    AuthSession.check_url.isnot(None),
                )
            )
            sessions = result.scalars().all()

            for session in sessions:
                state_path = SessionManager.state_file(session.session_name)
                if not state_path.exists():
                    skipped += 1
                    continue

                try:
                    state = SessionManager._load_state_json(state_path)
                    cookie_jar = {
                        c["name"]: c["value"] for c in state.get("cookies", [])
                    }
                    if not cookie_jar:
                        skipped += 1
                        continue

                    async with httpx.AsyncClient(
                        cookies=cookie_jar,
                        follow_redirects=True,
                        timeout=10.0,
                    ) as client:
                        # Lightweight ping — Canvas /api/v1/users/self returns small JSON
                        ping_url = (
                            session.check_url.rstrip("/") + "/api/v1/users/self"
                            if "/api/v1" not in session.check_url
                            else session.check_url
                        )
                        resp = await client.get(ping_url)

                    final_url = str(resp.url).lower()
                    if resp.status_code in (401, 403) or "login" in final_url:
                        logger.info(
                            "Canvas session expired (status=%d url=%s): %s",
                            resp.status_code, final_url, session.session_name,
                        )
                        session.is_valid = False
                        expired += 1
                    else:
                        # Merge any refreshed cookies back into the saved state
                        refreshed = dict(resp.cookies)
                        if refreshed:
                            for cookie in state.get("cookies", []):
                                if cookie["name"] in refreshed:
                                    cookie["value"] = refreshed[cookie["name"]]
                            state_path.write_text(
                                _encrypt_data(json.dumps(state, indent=2))
                            )
                            state_path.chmod(0o600)

                        session.last_validated_at = datetime.now(timezone.utc)
                        kept_alive += 1
                        logger.debug(
                            "Canvas session kept alive: %s", session.session_name
                        )

                except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
                    logger.warning(
                        "Canvas keep-alive failed for %s: %s",
                        session.session_name, e,
                    )
                    skipped += 1
                except Exception as e:  # httpx errors
                    if "httpx" in type(e).__module__ or "anyio" in type(e).__module__:
                        logger.warning(
                            "Canvas keep-alive HTTP error for %s: %s",
                            session.session_name, e,
                        )
                        skipped += 1
                    else:
                        raise

            await db.commit()

    except (SQLAlchemyError, ImportError, OSError) as e:
        logger.exception("Canvas keep-alive job failed")

    logger.info(
        "Canvas session keep-alive: kept_alive=%d expired=%d skipped=%d",
        kept_alive, expired, skipped,
    )
