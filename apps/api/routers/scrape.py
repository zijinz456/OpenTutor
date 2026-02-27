"""Scrape source management — CRUD for watched URLs + auth sessions."""

import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from models.course import Course
from models.scrape import ScrapeSource, AuthSession
from schemas.scrape import (
    ScrapeSourceCreate,
    ScrapeSourceUpdate,
    ScrapeSourceResponse,
    AuthLoginRequest,
    AuthSessionResponse,
)
from services.auth.dependency import get_current_user

router = APIRouter()


def _default_session_name(user_id: uuid.UUID, domain: str) -> str:
    """Build a stable, collision-resistant default session name."""
    from services.browser.session_manager import SessionManager

    return SessionManager.normalize_session_name(f"{user_id.hex}_{domain}")


# ── Scrape Sources ──


@router.get("/sources", response_model=list[ScrapeSourceResponse])
async def list_scrape_sources(
    course_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all watched URLs for auto-scraping."""
    query = select(ScrapeSource).where(ScrapeSource.user_id == user.id)
    if course_id:
        query = query.where(ScrapeSource.course_id == course_id)
    result = await db.execute(query.order_by(ScrapeSource.created_at.desc()))
    return result.scalars().all()


@router.post("/sources", response_model=ScrapeSourceResponse, status_code=201)
async def create_scrape_source(
    body: ScrapeSourceCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a URL to the auto-scrape watch list."""
    # Auto-detect auth_domain from URL if not provided
    auth_domain = body.auth_domain
    if body.requires_auth and not auth_domain:
        parsed = urlparse(str(body.url))
        auth_domain = parsed.netloc

    # Auto-generate session_name if not provided
    from services.browser.session_manager import SessionManager

    session_name = SessionManager.normalize_session_name(body.session_name) if body.session_name else None
    if body.requires_auth and not session_name:
        session_name = _default_session_name(user.id, auth_domain or "default")

    if not body.requires_auth:
        auth_domain = None
        session_name = None

    course_result = await db.execute(
        select(Course).where(Course.id == body.course_id, Course.user_id == user.id)
    )
    if not course_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Course not found")

    source = ScrapeSource(
        user_id=user.id,
        course_id=body.course_id,
        url=str(body.url),
        label=body.label,
        requires_auth=body.requires_auth,
        auth_domain=auth_domain,
        session_name=session_name,
        interval_hours=body.interval_hours,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.patch("/sources/{source_id}", response_model=ScrapeSourceResponse)
async def update_scrape_source(
    source_id: uuid.UUID,
    body: ScrapeSourceUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a watched URL's settings."""
    result = await db.execute(
        select(ScrapeSource).where(
            ScrapeSource.id == source_id,
            ScrapeSource.user_id == user.id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Scrape source not found")

    updates = body.model_dump(exclude_unset=True)

    from services.browser.session_manager import SessionManager

    # If auth is turned off, clear auth config fields.
    if updates.get("requires_auth") is False:
        updates["auth_domain"] = None
        updates["session_name"] = None

    # If auth is enabled and auth_domain is missing, derive from the source URL.
    if updates.get("requires_auth") is True and not updates.get("auth_domain"):
        updates["auth_domain"] = urlparse(source.url).netloc

    # Normalize user-provided session names.
    if "session_name" in updates and updates["session_name"]:
        updates["session_name"] = SessionManager.normalize_session_name(updates["session_name"])

    for field, value in updates.items():
        setattr(source, field, value)

    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
async def delete_scrape_source(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a URL from the watch list."""
    result = await db.execute(
        select(ScrapeSource).where(
            ScrapeSource.id == source_id,
            ScrapeSource.user_id == user.id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Scrape source not found")
    await db.delete(source)
    await db.commit()


@router.post("/sources/{source_id}/scrape-now")
async def scrape_now(
    source_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger an immediate scrape for a specific source."""
    result = await db.execute(
        select(ScrapeSource).where(
            ScrapeSource.id == source_id,
            ScrapeSource.user_id == user.id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Scrape source not found")

    from services.scraper.runner import _scrape_single

    changed = await _scrape_single(db, source, datetime.now(timezone.utc))
    await db.commit()

    return {
        "status": "ok",
        "content_changed": changed,
        "last_status": source.last_status,
    }


# ── Auth Sessions ──


@router.get("/auth/sessions", response_model=list[AuthSessionResponse])
async def list_auth_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all authentication sessions."""
    result = await db.execute(
        select(AuthSession)
        .where(AuthSession.user_id == user.id)
        .order_by(AuthSession.updated_at.desc())
    )
    return result.scalars().all()


@router.post("/auth/login", response_model=AuthSessionResponse)
async def auth_login(
    body: AuthLoginRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Login to an auth domain and save the session via Playwright."""
    from services.browser.session_manager import SessionManager
    from playwright.async_api import async_playwright

    session_name = _default_session_name(user.id, body.domain)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        success = await SessionManager.re_authenticate(
            browser, session_name, str(body.login_url), body.actions,
        )
        await browser.close()

    if not success:
        raise HTTPException(status_code=401, detail="Authentication failed")

    # Create or update AuthSession record
    result = await db.execute(
        select(AuthSession).where(
            AuthSession.session_name == session_name,
            AuthSession.user_id == user.id,
        )
    )
    auth_session = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if auth_session:
        auth_session.is_valid = True
        auth_session.last_validated_at = now
        auth_session.login_actions = body.actions
        auth_session.login_url = str(body.login_url)
        auth_session.check_url = str(body.check_url) if body.check_url else None
        auth_session.success_selector = body.success_selector
        auth_session.failure_selector = body.failure_selector
    else:
        auth_session = AuthSession(
            user_id=user.id,
            domain=body.domain,
            session_name=session_name,
            auth_type=body.auth_type,
            is_valid=True,
            last_validated_at=now,
            login_actions=body.actions,
            login_url=str(body.login_url),
            check_url=str(body.check_url) if body.check_url else None,
            success_selector=body.success_selector,
            failure_selector=body.failure_selector,
        )
        db.add(auth_session)

    await db.commit()
    await db.refresh(auth_session)
    return auth_session


@router.post("/auth/validate/{session_name}")
async def validate_auth_session(
    session_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate that an auth session is still active."""
    from services.browser.session_manager import SessionManager

    normalized_session_name = SessionManager.normalize_session_name(session_name)

    result = await db.execute(
        select(AuthSession).where(
            AuthSession.session_name == normalized_session_name,
            AuthSession.user_id == user.id,
        )
    )
    auth_session = result.scalar_one_or_none()
    if not auth_session:
        raise HTTPException(status_code=404, detail="Auth session not found")

    from playwright.async_api import async_playwright

    check_url = auth_session.check_url or f"https://{auth_session.domain}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        is_valid = await SessionManager.validate_session(
            browser,
            normalized_session_name,
            check_url,
            success_selector=auth_session.success_selector,
            failure_selector=auth_session.failure_selector,
        )
        await browser.close()

    auth_session.is_valid = is_valid
    auth_session.last_validated_at = datetime.now(timezone.utc)
    await db.commit()

    return {"session_name": normalized_session_name, "is_valid": is_valid}
