"""Unit tests for ``services.crawler.recursive_crawler`` (§14.5 v2.5 T1).

Five criteria per plan:
1. Canonicalization strips UTM + fragment (and lowercases host).
2. Depth cap respected — seed+links only at max_depth=1.
3. Canonical-hash dedup — same URL with/without utm visited once.
4. Same-origin gate — external host yields ``status="skip_origin"`` and is
   not fetched.
5. Fetch failure is swallowed — yields ``fetch_fail``, crawl continues.

httpx's built-in ``MockTransport`` is used for fetch interception so we
don't need to pull in ``respx`` or hit real URLs.
"""

from __future__ import annotations

import httpx
import pytest

from services.crawler.recursive_crawler import (
    CrawledPage,
    canonicalize_url,
    crawl_urls,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def _make_client(routes: dict[str, object]) -> httpx.AsyncClient:
    """Build an ``AsyncClient`` whose fetches are served from ``routes``.

    Each value in ``routes`` is either:
    - an HTML ``str`` → returned as 200 text/html.
    - an ``Exception`` instance → raised from the transport (simulates
      network failure; crawler must not propagate it).

    Keys are canonical URLs — tests pre-canonicalize so the mapping is
    unambiguous.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key not in routes:
            return httpx.Response(404, text="not found")
        value = routes[key]
        if isinstance(value, Exception):
            raise value
        assert isinstance(value, str)
        return httpx.Response(200, text=value, headers={"content-type": "text/html"})

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


async def _collect(agen) -> list[CrawledPage]:
    """Exhaust an async generator into a list (test helper)."""
    out: list[CrawledPage] = []
    async for page in agen:
        out.append(page)
    return out


# ── 1. Canonicalization ─────────────────────────────────────────────────────


def test_canonicalize_url_strips_utm_and_fragment() -> None:
    got = canonicalize_url("http://EX.com/a?utm_source=x&b=1#section")
    assert got == "http://ex.com/a?b=1"


def test_canonicalize_url_sorts_query_and_drops_fbclid() -> None:
    # Sanity companion: sorted params + fbclid scrubbed.
    got = canonicalize_url("https://Ex.COM/path?z=9&fbclid=abc&a=1")
    assert got == "https://ex.com/path?a=1&z=9"


# ── 2. Depth cap ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_depth_cap_respected() -> None:
    seed = "http://example.com/seed"
    # Seed links out to 3 children; children link onward (which must be
    # ignored at max_depth=1 since their depth would be 2).
    seed_html = '<a href="/a">A</a><a href="/b">B</a><a href="/c">C</a>'
    child_html = '<a href="/grandchild">GC</a>'

    routes = {
        "http://example.com/seed": seed_html,
        "http://example.com/a": child_html,
        "http://example.com/b": child_html,
        "http://example.com/c": child_html,
        # Grandchild route exists but must NEVER be fetched.
        "http://example.com/grandchild": "<p>should not be reached</p>",
    }

    client = _make_client(routes)
    try:
        pages = await _collect(
            crawl_urls([seed], max_depth=1, same_origin=True, client=client)
        )
    finally:
        await client.aclose()

    ok = [p for p in pages if p.status == "ok"]
    fetched_urls = {p.url for p in ok}
    assert fetched_urls == {
        "http://example.com/seed",
        "http://example.com/a",
        "http://example.com/b",
        "http://example.com/c",
    }
    # And critically — grandchild never shows up in any status.
    assert all("grandchild" not in p.url for p in pages)


# ── 3. Canonical dedup ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_dedup_canonical_hash() -> None:
    seed = "http://example.com/seed"
    # Seed links to /target twice: once clean, once with utm. Both must
    # canonicalize to the same URL → second occurrence is skipped.
    seed_html = (
        '<a href="/target">one</a><a href="/target?utm_source=newsletter">two</a>'
    )
    routes = {
        "http://example.com/seed": seed_html,
        "http://example.com/target": "<p>target body</p>",
    }

    client = _make_client(routes)
    try:
        pages = await _collect(
            crawl_urls([seed], max_depth=1, same_origin=True, client=client)
        )
    finally:
        await client.aclose()

    target_events = [p for p in pages if p.url.endswith("/target")]
    statuses = [p.status for p in target_events]
    # Exactly one ok + one skip_dedup for /target.
    assert statuses.count("ok") == 1
    assert statuses.count("skip_dedup") == 1
    assert len(target_events) == 2


# ── 4. Same-origin gate ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_same_origin_rejects_external() -> None:
    seed = "http://example.com/seed"
    seed_html = (
        '<a href="/internal">local</a><a href="https://external.com/page">remote</a>'
    )
    internal_fetched = {"count": 0}
    external_fetched = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "http://example.com/seed":
            return httpx.Response(200, text=seed_html)
        if url == "http://example.com/internal":
            internal_fetched["count"] += 1
            return httpx.Response(200, text="<p>internal</p>")
        if url.startswith("https://external.com"):
            external_fetched["count"] += 1
            return httpx.Response(200, text="<p>external</p>")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        pages = await _collect(
            crawl_urls([seed], max_depth=1, same_origin=True, client=client)
        )
    finally:
        await client.aclose()

    # External URL must appear with skip_origin status and must NOT be
    # fetched by the mock transport.
    external_events = [p for p in pages if "external.com" in p.url]
    assert len(external_events) == 1
    assert external_events[0].status == "skip_origin"
    assert external_events[0].html is None
    assert external_fetched["count"] == 0
    # Internal child was fetched exactly once (sanity).
    assert internal_fetched["count"] == 1


# ── 5. Fetch failure is swallowed ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_crawl_fetch_fail_does_not_raise() -> None:
    seed = "http://example.com/seed"
    seed_html = '<a href="/ok1">one</a><a href="/boom">boom</a><a href="/ok2">three</a>'

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "http://example.com/seed":
            return httpx.Response(200, text=seed_html)
        if url == "http://example.com/boom":
            raise httpx.ConnectError("simulated network failure")
        if url in {"http://example.com/ok1", "http://example.com/ok2"}:
            return httpx.Response(200, text="<p>ok body</p>")
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        # Must not raise.
        pages = await _collect(
            crawl_urls([seed], max_depth=1, same_origin=True, client=client)
        )
    finally:
        await client.aclose()

    by_url = {p.url: p for p in pages if p.url != "http://example.com/seed"}
    assert by_url["http://example.com/boom"].status == "fetch_fail"
    assert by_url["http://example.com/boom"].html is None
    # Siblings of the failing URL were still crawled successfully — the
    # generator did not abort after the ConnectError.
    assert by_url["http://example.com/ok1"].status == "ok"
    assert by_url["http://example.com/ok2"].status == "ok"
