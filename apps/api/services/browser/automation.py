"""Browser automation service — 3-layer cascade.

Layer 1: httpx (fast, no browser needed)
Layer 2: Scrapling (smart scraping with anti-bot, JS rendering)
Layer 3: Playwright + SessionManager
         (full browser automation with storageState persistence)

Reference: spec Phase 3 — 3-layer browser cascade.
"""

import asyncio
import logging
from urllib.parse import urljoin, urlparse

from libs.exceptions import ValidationError

logger = logging.getLogger(__name__)

_SAFE_IN_PAGE_SCHEMES = {"about", "blob", "data"}
_MAX_REDIRECTS = 5


async def _validate_public_url(url: str) -> None:
    """Reject non-HTTP and non-public destinations, including DNS results."""
    from libs.url_validation import validate_url, validate_url_dns

    validate_url(url)
    await validate_url_dns(url)


async def _guard_browser_request(route, request) -> None:
    """Abort browser network requests that could reach a local service."""
    if urlparse(request.url).scheme in _SAFE_IN_PAGE_SCHEMES:
        await route.continue_()
        return
    try:
        await _validate_public_url(request.url)
    except (ValidationError, ValueError) as exc:
        logger.warning("Blocked unsafe browser request to %s: %s", request.url, exc)
        await route.abort("blockedbyclient")
        return
    await route.continue_()


def _guard_scrapling_request(route, request) -> None:
    """Synchronous equivalent for Scrapling's browser-thread route."""
    if urlparse(request.url).scheme in _SAFE_IN_PAGE_SCHEMES:
        route.continue_()
        return
    try:
        from libs.url_validation import validate_url

        validate_url(request.url)
    except (ValidationError, ValueError) as exc:
        logger.warning("Blocked unsafe Scrapling request to %s: %s", request.url, exc)
        route.abort("blockedbyclient")
        return
    route.continue_()


def _setup_scrapling_page(page) -> None:
    """Install the navigation guard before Scrapling opens the target URL."""
    page.route("**/*", _guard_scrapling_request)


async def fetch_with_httpx(url: str, cookies: dict | None = None) -> str | None:
    """Layer 1: Simple HTTP fetch with httpx."""
    try:
        await _validate_public_url(url)
    except (ValidationError, ValueError) as e:
        logger.warning("URL validation failed for %s: %s", url, e)
        return None
    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=False, timeout=15) as client:
            current_url = url
            for _ in range(_MAX_REDIRECTS + 1):
                response = await client.get(current_url, cookies=cookies)
                if response.status_code == 200:
                    return response.text
                if not response.is_redirect:
                    logger.debug(
                        "httpx returned %s for %s", response.status_code, current_url
                    )
                    return None
                location = response.headers.get("location")
                if not location:
                    return None
                current_url = urljoin(current_url, location)
                try:
                    await _validate_public_url(current_url)
                except (ValidationError, ValueError) as exc:
                    logger.warning(
                        "Blocked unsafe HTTP redirect to %s: %s", current_url, exc
                    )
                    return None
            logger.warning("HTTP redirect limit exceeded for %s", url)
            return None
    except (httpx.HTTPError, OSError) as e:
        logger.debug("httpx failed for %s: %s", url, e)
        return None


async def fetch_with_scrapling(url: str) -> str | None:
    """Layer 2: Scrapling — smart scraping with anti-bot bypass and JS rendering.

    pip install scrapling
    Uses StealthyFetcher for sites that block bots.
    """
    try:
        await _validate_public_url(url)
    except (ValidationError, ValueError) as exc:
        logger.warning("URL validation failed for %s: %s", url, exc)
        return None
    try:
        from scrapling import StealthyFetcher

        fetcher = StealthyFetcher()
        page = await asyncio.to_thread(
            fetcher.fetch, url, page_setup=_setup_scrapling_page
        )
        if page.status == 200:
            return page.get_all_text() or page.html_content
        logger.debug(f"Scrapling returned status {page.status} for {url}")
        return None
    except ImportError:
        logger.debug("Scrapling not installed. Run: pip install scrapling")
        return None
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.warning("Scrapling failed for %s: %s", url, e)
        return None


async def fetch_with_browser(
    url: str,
    session_name: str = "default",
    actions: list[dict] | None = None,
) -> str | None:
    """Layer 3: Full browser automation with Playwright + SessionManager.

    Supports:
    - Session persistence via storageState (cookies + localStorage)
    - Custom actions (login flows, form filling)
    - JavaScript rendering
    """
    try:
        await _validate_public_url(url)
    except (ValidationError, ValueError) as e:
        logger.warning("URL validation failed for %s: %s", url, e)
        return None
    try:
        from playwright.async_api import async_playwright
        from services.browser.session_manager import SessionManager

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await SessionManager.create_context_with_state(
                browser, session_name
            )

            page = await context.new_page()
            await page.route("**/*", _guard_browser_request)
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Execute custom actions if provided
            if actions:
                for action in actions:
                    action_type = action.get("type")
                    if action_type == "click":
                        await page.click(action["selector"])
                    elif action_type == "fill":
                        await page.fill(action["selector"], action["value"])
                    elif action_type == "wait":
                        await page.wait_for_selector(action["selector"], timeout=10000)
                    elif action_type == "submit":
                        await page.click(
                            action.get("selector", "button[type='submit']")
                        )
                        await page.wait_for_load_state("networkidle")

            # Save session via storageState (cookies + localStorage)
            await SessionManager.save_state(context, session_name)

            # Get page content
            content = await page.content()
            await browser.close()

            return content

    except ImportError:
        logger.warning(
            "Playwright not installed. Run: pip install playwright "
            "&& playwright install"
        )
        return None
    except (OSError, RuntimeError, ConnectionError, TimeoutError):
        logger.exception("Browser automation failed for %s", url)
        return None
    except Exception:
        logger.exception("Browser automation failed for %s", url)
        return None


async def cascade_fetch(
    url: str,
    require_auth: bool = False,
    session_name: str = "default",
    cookies: dict | None = None,
) -> str | None:
    """3-layer cascade: try each layer in order until one succeeds.

    If require_auth=True, skips straight to browser layer with session.
    """
    if require_auth:
        return await fetch_with_browser(url, session_name)

    # Layer 1: httpx
    result = await fetch_with_httpx(url, cookies)
    if result:
        return result

    # Layer 2: Scrapling
    result = await fetch_with_scrapling(url)
    if result:
        return result

    # Layer 3: Browser
    return await fetch_with_browser(url, session_name)
