"""Unit tests for robots.txt gate + per-domain rate limit (§14.5 v2.5 T2).

Five criteria per plan:
1. ``is_url_allowed`` consults ``RobotFileParser.can_fetch`` and returns
   its value when the robots.txt fetch succeeds.
2. Fetch errors are fail-closed: ``is_url_allowed`` returns ``False`` when
   ``RobotFileParser.read`` raises.
3. Two successive calls for the same domain hit the robots cache — the
   underlying ``.read()`` is called exactly once.
4. ``_rate_limit_for_domain`` forces ≥ 1s delay between successive calls
   for the same domain by sleeping the remaining window.
5. End-to-end: a disallowed URL surfaces as ``CrawledPage(status="skip_robots")``
   and is never fetched by the httpx transport.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from services.crawler import robots as robots_mod
from services.crawler.recursive_crawler import (
    _DOMAIN_LAST_FETCH,
    _DOMAIN_LOCKS,
    _rate_limit_for_domain,
    crawl_urls,
)
from services.crawler.robots import is_url_allowed


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_module_state() -> None:
    """Ensure cache + rate-limit state does not leak across tests."""
    robots_mod._ROBOTS_CACHE.clear()
    _DOMAIN_LAST_FETCH.clear()
    _DOMAIN_LOCKS.clear()


# ── 1. robots.txt parsed and can_fetch consulted ────────────────────────────


@pytest.mark.asyncio
async def test_is_url_allowed_parses_robots_txt() -> None:
    """``.read()`` succeeds, ``.can_fetch`` returns True → allow."""
    with (
        patch("urllib.robotparser.RobotFileParser.read", return_value=None),
        patch(
            "urllib.robotparser.RobotFileParser.can_fetch", return_value=True
        ) as can_fetch,
    ):
        assert await is_url_allowed("http://ex.com/a") is True
        # Sanity — the URL (not just the domain) was passed through.
        args, _ = can_fetch.call_args
        assert args[1] == "http://ex.com/a"


# ── 2. Fail-closed on read() error ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_url_allowed_failclosed_on_fetch_error() -> None:
    """If ``.read()`` raises (500, timeout, DNS, …) we return False."""

    def _boom(self) -> None:
        raise OSError("simulated robots.txt fetch failure")

    with patch("urllib.robotparser.RobotFileParser.read", _boom):
        assert await is_url_allowed("http://ex.com/private") is False


# ── 3. Cached — read() called once across calls to same domain ──────────────


@pytest.mark.asyncio
async def test_is_url_allowed_cached() -> None:
    """Two calls for the same base → robots.txt fetched once."""
    with (
        patch(
            "urllib.robotparser.RobotFileParser.read", return_value=None
        ) as read_mock,
        patch("urllib.robotparser.RobotFileParser.can_fetch", return_value=True),
    ):
        await is_url_allowed("http://ex.com/a")
        await is_url_allowed("http://ex.com/b")  # same domain → no re-fetch
        assert read_mock.call_count == 1


# ── 4. Rate limiter sleeps to hold ≥ 1s between same-domain calls ──────────


@pytest.mark.asyncio
async def test_rate_limit_enforces_1s_between_requests_same_domain() -> None:
    """Second call within the 1s window must sleep the remaining delta.

    We drive ``loop.time()`` with a deterministic stub so the assertion is
    timing-insensitive: first call sees t=0 (no prior → no sleep), second
    call sees t=0.05 → expected sleep = 1.0 − 0.05 = 0.95s (≥ 0.9 margin).
    """
    # Sequence:   rate_limit #1 reads time once (write timestamp=0.0)
    #             rate_limit #2 reads time once (elapsed check → 0.05 < 1.0),
    #                            reads time once more (write timestamp=1.0).
    times = iter([0.0, 0.05, 1.0])

    class _FakeLoop:
        def time(self) -> float:
            return next(times)

    fake_loop = _FakeLoop()

    with (
        patch(
            "services.crawler.recursive_crawler.asyncio.get_event_loop",
            return_value=fake_loop,
        ),
        patch("services.crawler.recursive_crawler.asyncio.sleep") as sleep_mock,
    ):
        await _rate_limit_for_domain("ex.com", min_delay_s=1.0)
        await _rate_limit_for_domain("ex.com", min_delay_s=1.0)

    # First call had no prior timestamp → must not sleep.
    # Second call must sleep the remaining window (≥ 0.9s — allow slight
    # float arithmetic slack for future refactors).
    assert sleep_mock.call_count == 1
    (slept,), _ = sleep_mock.call_args
    assert slept >= 0.9


# ── 5. Integration: crawl respects robots ───────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_respects_robots() -> None:
    """Disallowed path yields ``skip_robots`` and is never fetched."""
    seed = "http://example.com/seed"
    seed_html = '<a href="/public">ok</a><a href="/private/secret">no</a>'

    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fetched.append(url)
        if url == "http://example.com/seed":
            return httpx.Response(200, text=seed_html)
        if url == "http://example.com/public":
            return httpx.Response(200, text="<p>public</p>")
        # A real server would also serve /private/secret — we assert it
        # never gets here, so any hit is a crawler bug.
        return httpx.Response(200, text="<p>should be blocked</p>")

    # Only disallow the /private/ subtree; everything else is allowed.
    # We bypass the cache + stdlib fetch by short-circuiting is_url_allowed.
    async def fake_allowed(url: str, user_agent: str = "LearnDopamineBot/1.0") -> bool:
        return "/private/" not in url

    # Zero out the rate limit so the test is fast (the limiter itself is
    # covered by test #4).
    async def fake_rate_limit(domain: str, min_delay_s: float = 1.0) -> None:
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with (
            patch(
                "services.crawler.recursive_crawler.is_url_allowed",
                side_effect=fake_allowed,
            ),
            patch(
                "services.crawler.recursive_crawler._rate_limit_for_domain",
                side_effect=fake_rate_limit,
            ),
        ):
            pages = []
            async for page in crawl_urls(
                [seed], max_depth=1, same_origin=True, client=client
            ):
                pages.append(page)
    finally:
        await client.aclose()

    private_events = [p for p in pages if "/private/secret" in p.url]
    assert len(private_events) == 1
    assert private_events[0].status == "skip_robots"
    assert private_events[0].html is None
    # And the mock transport never saw the disallowed URL.
    assert not any("/private/secret" in u for u in fetched)
    # Sanity — the allowed sibling was crawled successfully.
    ok = [p for p in pages if p.status == "ok"]
    assert {p.url for p in ok} == {
        "http://example.com/seed",
        "http://example.com/public",
    }
