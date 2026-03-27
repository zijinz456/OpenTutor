"""Canvas API HTTP client helpers.

Low-level utilities for authenticated Canvas REST API access:
- Session cookie loading from saved Playwright sessions
- Rate-limited API requests with exponential backoff
- Paginated API endpoint traversal
- HTML-to-text conversion utilities

Extracted from canvas_loader.py.
"""

import asyncio
import json
import logging
import re

import httpx  # noqa: F401 (re-exported for type usage)

logger = logging.getLogger(__name__)


class CanvasAuthExpiredError(Exception):
    """Raised when Canvas API returns 401 -- session cookies are stale."""
    pass


def _load_session_cookies(
    session_name: str | None,
    target_domain: str | None = None,
) -> dict[str, str]:
    """Load cookies from a saved Playwright session file for httpx use.

    Args:
        target_domain: If provided, only return cookies that match this domain.
    """
    if not session_name:
        return {}
    try:
        from services.browser.session_manager import SessionManager

        state_path = SessionManager.state_file(session_name)
        if not state_path.exists():
            logger.warning(
                "Canvas session state file not found for '%s' (expected: %s) — "
                "no cookies available for httpx requests",
                session_name, state_path,
            )
            return {}

        state = SessionManager._load_state_json(state_path)
        cookies = {}
        for cookie in state.get("cookies", []):
            cookie_domain = cookie.get("domain", "").lstrip(".")
            name = cookie["name"]

            if target_domain:
                td = target_domain.lstrip(".")
                if cookie_domain == td or td.endswith("." + cookie_domain):
                    cookies[name] = cookie["value"]
            else:
                cookies[name] = cookie["value"]
        return cookies
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.warning("Failed to load session cookies for %s: %s", session_name, e)
        return {}


# Canvas API concurrency limiter
_canvas_api_semaphore = asyncio.Semaphore(5)


async def _canvas_api_request_with_backoff(
    client, url: str, params: dict | None = None, max_retries: int = 3,
):
    """Make a Canvas API request with exponential backoff on rate limits."""
    async with _canvas_api_semaphore:
        for attempt in range(max_retries):
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                logger.warning(
                    "Canvas API rate limited, retrying after %.1fs (attempt %d/%d)",
                    retry_after, attempt + 1, max_retries,
                )
                await asyncio.sleep(min(retry_after, 30))
                continue
            return resp
        return resp


async def _canvas_api_paginate(
    client,
    url: str,
    params: dict | None = None,
    max_pages: int = 5,
) -> list[dict]:
    """Fetch all pages of a Canvas API endpoint using Link header pagination."""
    results = []
    next_url = url
    page_count = 0
    while next_url and page_count < max_pages:
        resp = await _canvas_api_request_with_backoff(
            client, next_url, params=params if page_count == 0 else None,
        )
        if resp.status_code != 200:
            break
        data = resp.json()
        if isinstance(data, list):
            results.extend(data)
        else:
            results.append(data)
        link_header = resp.headers.get("link", "")
        next_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
        page_count += 1
        params = None
    return results


def _canvas_clean_text(text: str) -> str:
    """Strip newlines and collapse whitespace in Canvas API text."""
    return re.sub(r"\s{2,}", " ", text.replace("\n", " ").replace("\r", " ")).strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to plain text using BeautifulSoup."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text(strip=True, separator="\n")
