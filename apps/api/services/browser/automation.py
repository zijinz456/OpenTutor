"""Browser automation service — 3-layer cascade.

Layer 1: httpx (fast, no browser needed)
Layer 2: Scrapling (smart scraping with anti-bot, JS rendering)
Layer 3: Playwright + SessionManager (full browser automation with storageState persistence)

Reference: spec Phase 3 — 3-layer browser cascade.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


async def fetch_with_httpx(url: str, cookies: dict | None = None) -> str | None:
    """Layer 1: Simple HTTP fetch with httpx."""
    try:
        from libs.url_validation import validate_url
        validate_url(url)
    except Exception as e:
        logger.warning("URL validation failed for %s: %s", url, e)
        return None
    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(url, cookies=cookies)
            if response.status_code == 200:
                return response.text
            logger.debug(f"httpx returned {response.status_code} for {url}")
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
        from scrapling import StealthyFetcher

        fetcher = StealthyFetcher()
        page = await asyncio.to_thread(fetcher.fetch, url)
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
        from libs.url_validation import validate_url
        validate_url(url)
    except Exception as e:
        logger.warning("URL validation failed for %s: %s", url, e)
        return None
    try:
        from playwright.async_api import async_playwright
        from services.browser.session_manager import SessionManager

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await SessionManager.create_context_with_state(browser, session_name)

            page = await context.new_page()
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
                        await page.click(action.get("selector", "button[type='submit']"))
                        await page.wait_for_load_state("networkidle")

            # Save session via storageState (cookies + localStorage)
            await SessionManager.save_state(context, session_name)

            # Get page content
            content = await page.content()
            await browser.close()

            return content

    except ImportError:
        logger.warning("Playwright not installed. Run: pip install playwright && playwright install")
        return None
    except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
        logger.exception("Browser automation failed for %s", url)
        return None
    except Exception as e:
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
