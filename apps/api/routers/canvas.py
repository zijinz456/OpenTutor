"""Canvas compatibility router.

Keeps legacy `/api/canvas/*` endpoints available while delegating to the
new scrape/session pipeline.
"""

import logging
from urllib.parse import urlparse
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends
from libs.exceptions import ExternalServiceError, PermissionDeniedError, ValidationError
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


class CanvasBrowserLoginRequest(BaseModel):
    canvas_url: AnyHttpUrl
    timeout_seconds: int = 300  # 5 minutes default


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


@router.post("/login", summary="Log in to Canvas LMS")
async def canvas_login(
    body: CanvasLoginRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy login endpoint bridged to session manager.

    For compatibility and security, this endpoint does not persist plaintext
    credentials in AuthSession.login_actions.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ExternalServiceError(service="Canvas", message="Playwright is required for Canvas login but is not installed. Install with: pip install playwright && playwright install chromium") from exc
    from routers.scrape import _default_session_name
    from services.browser.session_manager import SessionManager

    canvas_url = str(body.canvas_url).rstrip("/")
    login_url = f"{str(body.canvas_url).rstrip('/')}/login/canvas"
    domain = urlparse(canvas_url).netloc
    session_name = _default_session_name(user.id, domain)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            success = await SessionManager.re_authenticate(
                browser,
                session_name,
                login_url,
                _canvas_actions(body.username, body.password),
            )
            await browser.close()
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as exc:
        raise ExternalServiceError(
            service="Canvas",
            message=f"Browser automation failed: {exc}",
        ) from exc
    except Exception as exc:
        # Catch Playwright-specific errors (TimeoutError, Error, etc.)
        if "playwright" in type(exc).__module__:
            raise ExternalServiceError(
                service="Canvas",
                message=f"Browser automation failed: {exc}",
            ) from exc
        raise

    if not success:
        raise PermissionDeniedError("Canvas login failed")

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


@router.post("/browser-login", summary="Log in to Canvas via browser")
async def canvas_browser_login(
    body: CanvasBrowserLoginRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Open a visible browser window for manual Canvas login.

    Launches Playwright in headed (visible) mode so the user can complete
    SSO/Okta/MFA authentication manually.  The endpoint blocks until the
    user finishes logging in or the timeout is reached.  On success the
    session cookies are saved for subsequent authenticated scraping.
    """
    import asyncio

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise ExternalServiceError(service="Canvas", message="Playwright is required for browser login but is not installed. Install with: pip install playwright && playwright install chromium") from exc
    from routers.scrape import _default_session_name
    from services.browser.session_manager import SessionManager

    canvas_url = str(body.canvas_url).rstrip("/")
    domain = urlparse(canvas_url).netloc
    session_name = _default_session_name(user.id, domain)
    timeout = min(body.timeout_seconds, 600)  # cap at 10 minutes

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()

            try:
                try:
                    await page.goto(canvas_url, wait_until="domcontentloaded", timeout=30000)
                except Exception as nav_exc:
                    raise ExternalServiceError(
                        service="Canvas",
                        message=f"Failed to navigate to Canvas URL: {nav_exc}",
                    ) from nav_exc

                # Poll until the user completes login or timeout expires.
                # Success signals: URL returns to Canvas domain AND is no longer
                # on an SSO / login page.
                login_keywords = {"login", "auth", "okta", "sso", "saml", "adfs", "idp", "signin"}
                canvas_success_paths = {"/dashboard", "/courses", "/profile", "/calendar", "/grades"}

                success = False
                elapsed = 0.0
                poll_interval = 1.5
                # Track whether we've visited an auth page (external SSO domain or Canvas
                # login path).  Once we've been through auth and returned to the Canvas
                # domain on a non-login path, we know the login succeeded — even if the
                # final landing URL is just "/" (the root).
                visited_auth_page = False

                while elapsed < timeout:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                    try:
                        current_url = page.url.lower()
                    except (AttributeError, RuntimeError, OSError):
                        logger.debug("Browser closed during Canvas login polling")  # expected during user close
                        break  # browser was closed by user

                    parsed = urlparse(current_url)
                    path = parsed.path.rstrip("/")
                    host = parsed.netloc

                    # Track when we leave the Canvas domain (external SSO/OAuth flow)
                    if domain.lower() not in host:
                        visited_auth_page = True
                        logger.debug("Canvas login: on external auth host=%s", host)
                        continue

                    # Still on Canvas domain — check if we're on a login/SSO path
                    path_parts = set(path.split("/"))
                    on_login_path = bool(path_parts & login_keywords)

                    if on_login_path:
                        if not visited_auth_page:
                            visited_auth_page = True
                            logger.debug("Canvas login: on Canvas login path=%s", path)
                            continue
                        # We already went through auth and are back on Canvas domain
                        # but still on a login/callback path (e.g. /login/saml callback).
                        # Wait a bit for the redirect to settle rather than looping forever.
                        logger.debug(
                            "Canvas login: back on Canvas login path after auth, waiting for redirect (url=%s)",
                            current_url,
                        )
                        await asyncio.sleep(2)
                        continue

                    # We're back on the Canvas domain on a non-login path.
                    # If we already went through an auth page (SSO or login form), this
                    # means login completed — accept any URL including the root "/".
                    if visited_auth_page:
                        cookies = await context.cookies()
                        logger.info(
                            "Canvas browser login: SSO round-trip complete for %s (url=%s, cookies=%d)",
                            session_name,
                            current_url,
                            len(cookies),
                        )
                        success = True
                        break

                    # Fallback for cases where Canvas doesn't redirect to an external SSO:
                    # require a known Canvas page or any non-empty non-login path.
                    on_known_page = any(path.startswith(sp) for sp in canvas_success_paths)
                    not_on_login = "login" not in current_url
                    if on_known_page or (not_on_login and path != ""):
                        logger.info(
                            "Canvas browser login: detected logged-in page for %s (url=%s)",
                            session_name,
                            current_url,
                        )
                        success = True
                        break

                if success:
                    await SessionManager.save_state(context, session_name)
                    logger.info("Canvas browser login succeeded for %s", session_name)
            finally:
                await context.close()
                await browser.close()
    except ExternalServiceError:
        raise
    except PermissionDeniedError:
        raise
    except Exception as exc:
        raise ExternalServiceError(
            service="Canvas",
            message=f"Browser automation failed: {exc}",
        ) from exc

    if not success:
        raise PermissionDeniedError(
            "Canvas login timed out or was cancelled. Please try again."
        )

    # Upsert AuthSession record
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
        auth_session.login_url = None
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
                login_url=None,
                check_url=canvas_url,
            )
        )
    await db.commit()
    return {"status": "ok", "message": "Canvas session saved via browser login"}


class CanvasCourseInfoRequest(BaseModel):
    canvas_url: AnyHttpUrl


@router.post("/course-info", summary="Fetch Canvas course name")
async def canvas_course_info(
    body: CanvasCourseInfoRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch course name from Canvas API using saved session cookies."""
    from services.scraper.canvas_detector import detect_canvas_url
    from services.browser.session_manager import SessionManager
    from routers.scrape import _default_session_name

    canvas_url = str(body.canvas_url).rstrip("/")
    info = detect_canvas_url(canvas_url)
    if not info.is_canvas or not info.course_id:
        return {"name": None}

    domain = urlparse(canvas_url).netloc
    session_name = _default_session_name(user.id, domain)

    # Try Canvas REST API via authenticated session
    api_url = f"{info.api_base}/courses/{info.course_id}"
    try:
        from services.browser.automation import fetch_with_browser
        import json

        html = await fetch_with_browser(api_url, session_name=session_name)
        if html:
            # Canvas API returns JSON; the browser may wrap it in HTML
            # Try parsing as JSON directly first
            text = html.strip()
            # Strip HTML wrapper if present
            if text.startswith("<"):
                import re
                json_match = re.search(r"\{.*\}", text, re.DOTALL)
                if json_match:
                    text = json_match.group(0)
            data = json.loads(text)
            name = data.get("name") or data.get("course_code")
            if name:
                return {"name": name, "course_code": data.get("course_code", "")}
    except (json.JSONDecodeError, KeyError, OSError, RuntimeError):
        logger.debug("Failed to fetch Canvas course info via API", exc_info=True)

    return {"name": info.friendly_name}


@router.post("/sync", summary="Sync content from Canvas")
async def canvas_sync(
    body: CanvasSyncRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Legacy sync endpoint bridged to one-off scrape execution."""
    if body.api_token:
        raise ValidationError("Token-based Canvas sync is deprecated. Use authenticated scrape sessions.")

    from services.browser.automation import fetch_with_browser
    from services.parser.url import extract_text_from_html
    from routers.scrape import _default_session_name

    domain = urlparse(str(body.canvas_url)).netloc
    session_name = _default_session_name(user.id, domain)
    dashboard_url = f"{str(body.canvas_url).rstrip('/')}/dashboard"
    html = await fetch_with_browser(dashboard_url, session_name=session_name)
    if not html:
        raise PermissionDeniedError("Canvas session expired or unavailable. Please login again via /api/canvas/login.")
    text = extract_text_from_html(html)
    return {
        "status": "ok",
        "message": "Canvas sync preview completed",
        "content_preview": text[:500] if text else "",
    }
