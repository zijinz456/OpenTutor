"""Canvas-specific scraping strategy.

Handles Canvas LMS REST API deep extraction with session-based authentication,
re-authentication via stored login actions, and ingestion pipeline integration.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.scrape import ScrapeSource, AuthSession
from services.agent.background_runtime import track_background_task

logger = logging.getLogger(__name__)

try:
    import xxhash as _xxhash
except ImportError:
    _xxhash = None


def _content_hash(content: str) -> str:
    if _xxhash:
        return _xxhash.xxh64(content.encode()).hexdigest()
    return hashlib.sha256(content.encode()).hexdigest()


async def scrape_canvas(
    db: AsyncSession, source: ScrapeSource, now: datetime
) -> bool:
    """Canvas-specific scrape using REST API deep extraction.

    Uses session cookies for authenticated API access. On 401, marks session
    invalid and triggers re-authentication if login_actions are available.
    """
    from services.ingestion.document_loader import (
        _try_canvas_api_deep, CanvasAuthExpiredError,
    )
    from services.ingestion.pipeline import run_ingestion_pipeline
    from services.scraper.runner import _maybe_disable_source, _mark_auth_expired, _fire_background_embed

    try:
        deep_result = await _try_canvas_api_deep(source.url, session_name=source.session_name)
    except CanvasAuthExpiredError:
        logger.warning("Canvas session expired for %s — attempting re-auth", source.url)

        re_authed = await _try_canvas_reauth(db, source)
        if re_authed:
            try:
                deep_result = await _try_canvas_api_deep(source.url, session_name=source.session_name)
            except CanvasAuthExpiredError:
                deep_result = None
        else:
            deep_result = None

        if not deep_result:
            _mark_auth_expired(source)
            source.consecutive_failures = (source.consecutive_failures or 0) + 1
            source.last_scraped_at = now
            source.last_error = "Canvas session expired — please re-login"
            _maybe_disable_source(source)
            return False

    if not deep_result or not deep_result.content:
        source.last_status = "failed"
        source.last_error = "No content extracted from Canvas API"
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        source.last_scraped_at = now
        _maybe_disable_source(source)
        return False

    # Change detection
    content = deep_result.content
    chash = _content_hash(content)
    if chash == source.last_content_hash:
        source.last_scraped_at = now
        source.last_status = "success"
        source.last_error = None
        source.consecutive_failures = 0
        logger.info("Canvas content unchanged for %s", source.url)
        return False

    # Run through ingestion pipeline with the extracted content
    job = await run_ingestion_pipeline(
        db=db,
        user_id=source.user_id,
        url=source.url,
        filename=source.label or deep_result.title or "Canvas Course",
        course_id=source.course_id,
        pre_fetched_html=None,
        session_name=source.session_name,
    )

    source.last_scraped_at = now
    source.last_ingestion_id = job.id

    if job.status != "failed":
        source.last_content_hash = chash
        source.last_status = "success"
        source.last_error = None
        source.consecutive_failures = 0

        # Process discovered Canvas files in background
        if deep_result.file_urls:
            from services.ingestion.pipeline import ingest_canvas_files
            from database import async_session as _async_session

            async def _bg_canvas_files():
                await ingest_canvas_files(
                    db_factory=_async_session,
                    user_id=source.user_id,
                    course_id=source.course_id,
                    file_urls=deep_result.file_urls,
                    session_name=source.session_name,
                    canvas_domain=source.auth_domain or "",
                )
            track_background_task(asyncio.create_task(_bg_canvas_files()))

        if (job.dispatched_to or {}).get("content_tree", 0) > 0:
            _fire_background_embed(source.course_id)
        return True

    source.last_status = "failed"
    source.last_error = job.error_message or "Canvas ingestion failed"
    source.consecutive_failures = (source.consecutive_failures or 0) + 1
    _maybe_disable_source(source)
    return False


async def _try_canvas_reauth(db: AsyncSession, source: ScrapeSource) -> bool:
    """Try to re-authenticate a Canvas session using stored login actions."""
    auth_session = await _get_auth_session(db, source.user_id, source.session_name)
    if not auth_session or not auth_session.login_actions:
        return False

    try:
        from playwright.async_api import async_playwright
        from services.browser.session_manager import SessionManager

        check_url = (
            auth_session.check_url
            or (f"https://{source.auth_domain}" if source.auth_domain else source.url)
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            re_auth_ok = await SessionManager.re_authenticate(
                browser,
                source.session_name,
                auth_session.login_url or check_url,
                auth_session.login_actions,
            )
            await browser.close()

            if re_auth_ok:
                auth_session.is_valid = True
                auth_session.last_validated_at = datetime.now(timezone.utc)
                logger.info("Canvas re-authentication succeeded for %s", source.auth_domain)
                return True
            else:
                auth_session.is_valid = False
                auth_session.last_validated_at = datetime.now(timezone.utc)
                return False
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.exception("Canvas re-authentication failed")
        return False


async def _get_auth_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    session_name: str,
) -> AuthSession | None:
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.session_name == session_name,
            AuthSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()
