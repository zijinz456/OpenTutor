"""Scrape runner — orchestrates periodic authenticated scraping.

Called by the scheduler's scrape_refresh_job.
For each enabled ScrapeSource:
1. Check if scrape is due (interval_hours elapsed)
2. If requires_auth, validate session; re-authenticate if needed
3. Fetch content (authenticated or plain)
4. Compute content hash; skip if unchanged
5. Run ingestion pipeline on changed content
6. Update ScrapeSource status
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scrape import ScrapeSource, AuthSession
from services.agent.background_runtime import track_background_task

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5

try:
    import xxhash as _xxhash
except ImportError:
    _xxhash = None


async def run_scrape_refresh(db: AsyncSession) -> dict:
    """Main entry point: process all enabled ScrapeSource records."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(ScrapeSource).where(ScrapeSource.enabled.is_(True))
    )
    sources = result.scalars().all()
    logger.info("Scrape refresh: %d enabled sources", len(sources))

    scraped, skipped, failed = 0, 0, 0

    for source in sources:
        if source.last_scraped_at:
            next_due = source.last_scraped_at + timedelta(hours=source.interval_hours)
            if now < next_due:
                skipped += 1
                continue
        try:
            changed = await _scrape_single(db, source, now)
            if source.last_status in {"failed", "auth_expired"}:
                failed += 1
            elif changed:
                scraped += 1
            else:
                skipped += 1
        except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
            logger.exception("Scrape failed for %s", source.url)
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
            source.last_status = "failed"
            source.last_error = str(e)[:500]
            source.last_scraped_at = now
            failed += 1
            _maybe_disable_source(source)

    await db.flush()
    logger.info(
        "Scrape refresh complete: scraped=%d skipped=%d failed=%d",
        scraped, skipped, failed,
    )
    return {"scraped": scraped, "skipped": skipped, "failed": failed}


async def _scrape_single(
    db: AsyncSession, source: ScrapeSource, now: datetime
) -> bool:
    """Scrape a single source. Returns True if content changed and was re-ingested."""
    # Canvas sources: use Canvas REST API deep extraction
    if source.source_type == "canvas" and source.session_name:
        from services.scraper.canvas_scraper import scrape_canvas
        return await scrape_canvas(db, source, now)

    content = None
    if source.requires_auth:
        content = await _authenticated_fetch(db, source)
    else:
        from services.browser.automation import cascade_fetch
        content = await cascade_fetch(source.url)

    if not content:
        if source.last_status == "auth_expired":
            source.last_error = "Authentication expired"
        else:
            source.last_status = "failed"
            source.last_error = "No content returned"
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        source.last_scraped_at = now
        _maybe_disable_source(source)
        return False

    # Change detection via content hash
    if _xxhash:
        content_hash = _xxhash.xxh64(content.encode()).hexdigest()
    else:
        content_hash = hashlib.sha256(content.encode()).hexdigest()
    if content_hash == source.last_content_hash:
        source.last_scraped_at = now
        source.last_status = "success"
        source.last_error = None
        source.consecutive_failures = 0
        logger.info("Content unchanged for %s", source.url)
        return False

    return await _process_generic_content(db, source, content, content_hash, now)


async def _process_generic_content(
    db: AsyncSession, source: ScrapeSource, content: str,
    content_hash: str, now: datetime,
) -> bool:
    """Process generic web pages through the ingestion pipeline."""
    from services.ingestion.pipeline import run_ingestion_pipeline

    job = await run_ingestion_pipeline(
        db=db,
        user_id=source.user_id,
        url=source.url,
        filename=source.label or source.url.split("/")[-1] or "scraped_page",
        course_id=source.course_id,
        file_bytes=content.encode(),
        pre_fetched_html=content,
    )

    source.last_scraped_at = now
    source.last_ingestion_id = job.id

    if job.status == "completed":
        source.last_content_hash = content_hash
        source.last_status = "success"
        source.last_error = None
        source.consecutive_failures = 0
        if (job.dispatched_to or {}).get("content_tree", 0) > 0:
            _fire_background_embed(source.course_id)
        return True

    source.last_status = "failed"
    source.last_error = job.error_message or "Ingestion failed"
    source.consecutive_failures = (source.consecutive_failures or 0) + 1
    _maybe_disable_source(source)
    return False


async def _authenticated_fetch(db: AsyncSession, source: ScrapeSource) -> str | None:
    """Fetch a URL that requires authentication via SessionManager."""
    from playwright.async_api import async_playwright
    from services.browser.session_manager import SessionManager

    session_name = source.session_name
    if not session_name:
        logger.error("No session_name for auth source %s", source.url)
        return None

    auth_session = await _get_auth_session(db, source.user_id, session_name)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        check_url = (
            (auth_session.check_url if auth_session and auth_session.check_url else None)
            or (f"https://{source.auth_domain}" if source.auth_domain else source.url)
        )
        is_valid = await SessionManager.validate_session(
            browser, session_name, check_url,
            success_selector=auth_session.success_selector if auth_session else None,
            failure_selector=auth_session.failure_selector if auth_session else None,
        )
        if not is_valid and auth_session and auth_session.login_actions:
            logger.info("Session expired for %s, re-authenticating...", session_name)
            re_auth_ok = await SessionManager.re_authenticate(
                browser, session_name,
                auth_session.login_url or check_url,
                auth_session.login_actions,
            )
            if not re_auth_ok:
                auth_session.is_valid = False
                auth_session.last_validated_at = datetime.now(timezone.utc)
                _mark_auth_expired(source)
                await browser.close()
                return None
            auth_session.is_valid = True
            auth_session.last_validated_at = datetime.now(timezone.utc)
        elif not is_valid:
            if auth_session:
                auth_session.is_valid = False
                auth_session.last_validated_at = datetime.now(timezone.utc)
            _mark_auth_expired(source)
            await browser.close()
            return None

        content = await SessionManager.fetch_with_session(browser, session_name, source.url)
        await browser.close()
        return content


async def _get_auth_session(
    db: AsyncSession, user_id: uuid.UUID, session_name: str,
) -> AuthSession | None:
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.session_name == session_name,
            AuthSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


def _maybe_disable_source(source: ScrapeSource) -> None:
    if source.consecutive_failures >= MAX_CONSECUTIVE_FAILURES and source.enabled:
        source.enabled = False
        logger.warning(
            "Auto-disabled scrape source %s after %d failures",
            source.url, source.consecutive_failures,
        )
        _notify_scrape_disabled(source)


def _mark_auth_expired(source: ScrapeSource) -> None:
    """Set auth_expired and notify once per transition."""
    already_expired = source.last_status == "auth_expired"
    source.last_status = "auth_expired"
    if not already_expired:
        _notify_auth_expired(source)


def _fire_background_embed(course_id: uuid.UUID):
    """Fire-and-forget background embedding computation."""
    async def _embed():
        try:
            from database import async_session
            from services.embedding.content import embed_course_content
            async with async_session() as db:
                await embed_course_content(db, course_id)
                await db.commit()
        except (ConnectionError, TimeoutError, RuntimeError, ValueError, OSError) as e:
            logger.exception("Background embedding failed for course %s: %s", course_id, e)
    track_background_task(asyncio.create_task(_embed()))


def _notify_scrape_disabled(source: ScrapeSource):
    from services.scheduler.engine import _push_notification
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_push_notification(
            source.user_id,
            "Auto-Scrape Disabled",
            f"Scraping for '{source.label or source.url}' was disabled after "
            f"{source.consecutive_failures} consecutive failures. "
            "Please check the URL and re-enable.",
            category="scrape_alert",
        ))
    except RuntimeError:
        logger.debug("No running event loop — scrape-disabled notification skipped")


def _notify_auth_expired(source: ScrapeSource):
    from services.scheduler.engine import _push_notification
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_push_notification(
            source.user_id,
            "Authentication Expired",
            f"Session expired for '{source.auth_domain or source.url}'. "
            "Please re-login to continue auto-scraping.",
            category="scrape_auth_expired",
        ))
    except RuntimeError:
        logger.debug("No running event loop — auth-expired notification skipped")
