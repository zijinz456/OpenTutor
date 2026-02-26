"""Browser automation service — 3-layer cascade.

Layer 1: httpx (fast, no browser needed)
Layer 2: Scrapling (smart scraping with anti-bot, JS rendering)
Layer 3: browser-use (full browser automation with Playwright)

Reference: spec Phase 3 — 3-layer browser cascade.

For Canvas LMS: uses browser-use to handle OAuth login,
persist session cookies, and extract authenticated content.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Session storage path
SESSION_DIR = Path("./sessions")
SESSION_DIR.mkdir(exist_ok=True)


async def fetch_with_httpx(url: str, cookies: dict | None = None) -> str | None:
    """Layer 1: Simple HTTP fetch with httpx."""
    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(url, cookies=cookies)
            if response.status_code == 200:
                return response.text
            logger.debug(f"httpx returned {response.status_code} for {url}")
            return None
    except Exception as e:
        logger.debug(f"httpx failed for {url}: {e}")
        return None


async def fetch_with_scrapling(url: str) -> str | None:
    """Layer 2: Scrapling — smart scraping with anti-bot bypass and JS rendering.

    pip install scrapling
    Uses StealthyFetcher for sites that block bots.
    """
    try:
        from scrapling import StealthyFetcher

        fetcher = StealthyFetcher()
        page = fetcher.fetch(url)
        if page.status == 200:
            return page.get_all_text() or page.html_content
        logger.debug(f"Scrapling returned status {page.status} for {url}")
        return None
    except ImportError:
        logger.debug("Scrapling not installed. Run: pip install scrapling")
        return None
    except Exception as e:
        logger.debug(f"Scrapling failed for {url}: {e}")
        return None


async def fetch_with_browser(
    url: str,
    session_name: str = "default",
    actions: list[dict] | None = None,
) -> str | None:
    """Layer 3: Full browser automation with Playwright.

    Supports:
    - Session persistence (cookies saved/loaded)
    - Custom actions (login flows, form filling)
    - JavaScript rendering
    """
    try:
        from playwright.async_api import async_playwright

        session_file = SESSION_DIR / f"{session_name}_cookies.json"

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            # Load saved session if exists
            if session_file.exists():
                cookies = json.loads(session_file.read_text())
                await context.add_cookies(cookies)
                logger.info(f"Loaded session: {session_name}")

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

            # Save session cookies
            cookies = await context.cookies()
            session_file.write_text(json.dumps(cookies, indent=2))

            # Get page content
            content = await page.content()
            await browser.close()

            return content

    except ImportError:
        logger.warning("Playwright not installed. Run: pip install playwright && playwright install")
        return None
    except Exception as e:
        logger.warning(f"Browser automation failed: {e}")
        return None


async def cascade_fetch(
    url: str,
    require_auth: bool = False,
    session_name: str = "default",
    cookies: dict | None = None,
) -> str | None:
    """3-layer cascade: try each layer in order until one succeeds.

    If require_auth=True, skips straight to browser layer.
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


async def canvas_login(
    canvas_url: str,
    username: str,
    password: str,
) -> bool:
    """Login to Canvas LMS and save session cookies.

    Uses browser-use for OAuth login flow.
    Session is persisted for future API calls.
    """
    login_url = f"{canvas_url}/login/canvas"

    result = await fetch_with_browser(
        login_url,
        session_name="canvas",
        actions=[
            {"type": "fill", "selector": "#pseudonym_session_unique_id", "value": username},
            {"type": "fill", "selector": "#pseudonym_session_password", "value": password},
            {"type": "submit", "selector": "button[type='submit']"},
            {"type": "wait", "selector": "#dashboard"},
        ],
    )

    return result is not None


async def canvas_fetch(url: str) -> str | None:
    """Fetch a Canvas page using saved session."""
    session_file = SESSION_DIR / "canvas_cookies.json"

    if session_file.exists():
        cookies_list = json.loads(session_file.read_text())
        cookies_dict = {c["name"]: c["value"] for c in cookies_list}
        # Try httpx first with saved cookies
        result = await fetch_with_httpx(url, cookies_dict)
        if result:
            return result

    # Fallback to browser with session
    return await fetch_with_browser(url, session_name="canvas")
