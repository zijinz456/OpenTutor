"""Canvas compatibility router.

Keeps legacy `/api/canvas/*` endpoints available while delegating to the
new scrape/session pipeline.
"""

from urllib.parse import urlparse
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, AnyHttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.scrape import AuthSession
from models.user import User
from services.auth.dependency import get_current_user

router = APIRouter()


class CanvasLoginRequest(BaseModel):
    canvas_url: AnyHttpUrl
    username: str
    password: str


class CanvasSyncRequest(BaseModel):
    canvas_url: AnyHttpUrl
    api_token: str | None = None
    course_ids: list[int] | None = None


def _canvas_actions(username: str, password: str) -> list[dict]:
    return [
        {"type": "fill", "selector": "#pseudonym_session_unique_id", "value": username},
        {"type": "fill", "selector": "#pseudonym_session_password", "value": password},
        {"type": "submit", "selector": "button[type='submit']"},
        {"type": "wait", "selector": "#dashboard"},
    ]


@router.post("/login")
async def canvas_login(
    body: CanvasLoginRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy login endpoint bridged to session manager.

    For compatibility and security, this endpoint does not persist plaintext
    credentials in AuthSession.login_actions.
    """
    from playwright.async_api import async_playwright
    from routers.scrape import _default_session_name
    from services.browser.session_manager import SessionManager

    canvas_url = str(body.canvas_url).rstrip("/")
    login_url = f"{str(body.canvas_url).rstrip('/')}/login/canvas"
    domain = urlparse(canvas_url).netloc
    session_name = _default_session_name(user.id, domain)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        success = await SessionManager.re_authenticate(
            browser,
            session_name,
            login_url,
            _canvas_actions(body.username, body.password),
        )
        await browser.close()

    if not success:
        raise HTTPException(status_code=401, detail="Canvas login failed")

    result = await db.execute(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.session_name == session_name,
        )
    )
    auth_session = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if auth_session:
        auth_session.is_valid = True
        auth_session.last_validated_at = now
        auth_session.login_actions = None
        auth_session.login_url = login_url
        auth_session.check_url = canvas_url
    else:
        db.add(
            AuthSession(
                user_id=user.id,
                domain=domain,
                session_name=session_name,
                auth_type="cookie",
                is_valid=True,
                last_validated_at=now,
                login_actions=None,
                login_url=login_url,
                check_url=canvas_url,
            )
        )
    await db.commit()
    return {"status": "ok", "message": "Canvas session saved"}


@router.post("/sync")
async def canvas_sync(
    body: CanvasSyncRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy sync endpoint bridged to one-off scrape execution."""
    if body.api_token:
        raise HTTPException(
            status_code=410,
            detail="Token-based Canvas sync is deprecated. Use authenticated scrape sessions.",
        )

    from services.browser.automation import fetch_with_browser
    from services.parser.url import extract_text_from_html
    from routers.scrape import _default_session_name

    domain = urlparse(str(body.canvas_url)).netloc
    session_name = _default_session_name(user.id, domain)
    dashboard_url = f"{str(body.canvas_url).rstrip('/')}/dashboard"
    html = await fetch_with_browser(dashboard_url, session_name=session_name)
    if not html:
        raise HTTPException(
            status_code=401,
            detail="Canvas session expired or unavailable. Please login again via /api/canvas/login.",
        )
    text = extract_text_from_html(html)
    return {
        "status": "ok",
        "message": "Canvas sync preview completed",
        "content_preview": text[:500] if text else "",
    }
