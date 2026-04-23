"""BFS recursive URL crawler — core primitives (§14.5 v2.5 T1).

Scope of this module (architect defaults):
- **Same-origin filter ON by default** (F2): only URLs sharing the seed's
  ``(scheme, netloc)`` are followed. ``path_prefix`` is an optional further
  constraint so ``docs.python.org/3/tutorial/`` does not drag in
  ``/3/library/`` blog feeds.
- **Stdlib-only HTTP via ``httpx.AsyncClient``** (F3): no Playwright, no
  Scrapling. Crawl-tier pages are by definition cheap HTML; heavy fallbacks
  belong to the per-page ingestion pipeline, not the crawler.
- **No robots.txt, no rate-limit, no DB writes** — those are T2/T3 scope.
- **Never raises on fetch failure** — yields ``status="fetch_fail"`` so the
  caller can decide its own logging/accounting policy.

Canonicalization strips ``utm_*``, ``fbclid``, ``gclid``, session query
params, and URL fragments; lowercases the host; sorts remaining query
params so ``?b=1&a=2`` and ``?a=2&b=1`` hash identically.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from typing import AsyncIterator, NamedTuple
from urllib.parse import parse_qsl, urldefrag, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from services.crawler.robots import is_url_allowed

logger = logging.getLogger(__name__)

# Query-param prefixes / names stripped during canonicalization. Kept
# conservative — only well-known tracking noise. Unknown params survive.
_TRACKING_PREFIXES: tuple[str, ...] = ("utm_",)
_TRACKING_EXACT: frozenset[str] = frozenset(
    {
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "yclid",
        "_ga",
        "ref",
        "ref_src",
    }
)

# Default User-Agent. A tighter identifiable UA belongs to T2 (robots.txt
# etiquette); here we only need *something* that won't be blanket-blocked.
_DEFAULT_UA = "LearnDopamine-Crawler/1.0 (+personal-learning)"

# httpx timeouts chosen to fail fast without tripping on slow docs sites.
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)


class CrawledPage(NamedTuple):
    """A single BFS visitation event.

    ``html`` is ``None`` whenever ``status`` is not ``"ok"`` — callers should
    not attempt to parse it in those cases.

    Status values:
    - ``ok``           — fetched, HTML returned.
    - ``skip_depth``   — URL was beyond ``max_depth`` (reserved; BFS gates
                         this at enqueue time so it is uncommon in practice).
    - ``skip_dedup``   — canonical form already visited.
    - ``skip_origin``  — different ``(scheme, netloc)`` than the seed and
                         ``same_origin=True``.
    - ``skip_prefix``  — origin matches but path does not start with
                         ``path_prefix``.
    - ``skip_robots``  — ``robots.txt`` disallows this URL (or the fetch
                         failed and we fail-closed). See ``services.crawler.robots``.
    - ``fetch_fail``   — httpx raised or returned non-2xx.
    """

    url: str
    depth: int
    html: str | None
    status: str


def canonicalize_url(url: str) -> str:
    """Return a stable canonical form suitable for dedup hashing.

    Transformations (all idempotent):
    1. Drop fragment (``#section`` — never sent to the server anyway).
    2. Lowercase scheme and host (RFC 3986 §6.2.2.1 — host is
       case-insensitive; path is not, so we leave it alone).
    3. Drop tracking query params (``utm_*``, ``fbclid``, etc.).
    4. Sort remaining query params by (key, value) so ordering does not
       create phantom duplicates.

    Port, userinfo, path, and unknown query params are preserved verbatim.
    """
    # Strip fragment first — ``urldefrag`` is the stdlib blessed way.
    defragged, _ = urldefrag(url)
    parsed = urlparse(defragged)

    # Lowercase only the host portion of netloc — preserve userinfo/port.
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, host_part = netloc.rsplit("@", 1)
        host_part = host_part.lower()
        netloc = f"{userinfo}@{host_part}"
    else:
        netloc = netloc.lower()

    # Filter + sort query params. ``keep_blank_values=True`` because empty
    # values can be semantically meaningful (e.g. ``?foo=``).
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in _TRACKING_EXACT:
            continue
        if any(lowered.startswith(prefix) for prefix in _TRACKING_PREFIXES):
            continue
        kept.append((key, value))
    kept.sort()
    # Reconstruct query without url-escaping that the caller did not ask for.
    new_query = "&".join(f"{k}={v}" if v != "" else f"{k}=" for k, v in kept)

    return urlunparse(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path,
            parsed.params,
            new_query,
            "",  # fragment — intentionally dropped
        )
    )


def _origin(url: str) -> tuple[str, str]:
    """Return ``(scheme, netloc)`` tuple used for same-origin comparison."""
    p = urlparse(url)
    return (p.scheme.lower(), p.netloc.lower())


def _extract_links(html: str, base_url: str) -> list[str]:
    """Pull absolute ``href`` targets from anchor tags.

    Uses the already-bundled ``beautifulsoup4`` (see ``pyproject.toml``).
    Relative URLs are resolved against ``base_url``. Non-HTTP schemes
    (``mailto:``, ``javascript:``, ``tel:``) are discarded.
    """
    out: list[str] = []
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        raw = anchor["href"]
        # bs4 types ``href`` as ``str | AttributeValueList`` because some
        # attrs (like ``class``) are list-valued; ``href`` is always a str
        # in practice, but we coerce defensively to keep ty happy.
        if not isinstance(raw, str):
            continue
        href = raw.strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        scheme = urlparse(absolute).scheme.lower()
        if scheme not in {"http", "https"}:
            continue
        out.append(absolute)
    return out


# ── Per-domain rate limiter ─────────────────────────────────────────────────
#
# Module-level state intentional: every ``crawl_urls`` invocation shares the
# same politeness window per domain, so two concurrent crawls of
# ``docs.python.org`` cannot gang up and exceed 1 req/sec combined. The lock
# per domain is created lazily via ``defaultdict``; ``asyncio.Lock`` is
# bound to the running event loop on first await, which is fine because all
# crawler work runs on the same FastAPI loop.

_DOMAIN_LOCKS: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_DOMAIN_LAST_FETCH: dict[str, float] = {}


async def _rate_limit_for_domain(domain: str, min_delay_s: float = 1.0) -> None:
    """Sleep until at least ``min_delay_s`` has passed since the last fetch.

    Holds the per-domain lock across the sleep + timestamp-write so that two
    coroutines racing on the same domain cannot both observe the "old"
    timestamp and skip the wait. The lock is released before the actual HTTP
    request runs — concurrency cap for cross-domain crawls is a separate
    concern (caller's responsibility via ``asyncio.Semaphore`` if wanted).
    """
    loop = asyncio.get_event_loop()
    async with _DOMAIN_LOCKS[domain]:
        last = _DOMAIN_LAST_FETCH.get(domain)
        if last is not None:
            elapsed = loop.time() - last
            if elapsed < min_delay_s:
                await asyncio.sleep(min_delay_s - elapsed)
        _DOMAIN_LAST_FETCH[domain] = loop.time()


async def _fetch(client: httpx.AsyncClient, url: str) -> str | None:
    """Fetch ``url``; return HTML text on 2xx, ``None`` on any failure.

    Intentionally broad ``except`` — crawler must never raise upstream.
    """
    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        # Some servers lie about charsets; httpx already handles the common
        # cases via apparent_encoding. We don't re-decode bytes here.
        return response.text
    except Exception as exc:  # noqa: BLE001 — crawler contract is no-raise
        logger.debug("crawler fetch failed for %s: %s", url, exc)
        return None


async def crawl_urls(
    seed_urls: list[str],
    *,
    max_depth: int = 3,
    max_pages: int = 100,
    max_total_html_bytes: int = 500 * 1024 * 1024,  # 500 MiB
    same_origin: bool = True,
    path_prefix: str | None = None,
    client: httpx.AsyncClient | None = None,
) -> AsyncIterator[CrawledPage]:
    """BFS crawl seeded by ``seed_urls``.

    Yields one :class:`CrawledPage` per URL *considered* (including skips)
    so callers can build progress counters without re-walking the queue.

    Stops cleanly when any cap is hit:
    - ``max_pages`` successful fetches.
    - ``max_total_html_bytes`` cumulative HTML body bytes.
    - Empty queue.

    ``max_depth`` is 0-based: ``0`` means seed-only, ``1`` means seed + its
    direct links, etc.

    ``client`` may be passed for test injection / connection reuse. When
    omitted, a short-lived ``httpx.AsyncClient`` is created and closed.
    """
    if not seed_urls:
        return

    seen_canonical: set[str] = set()
    queue: deque[tuple[str, int]] = deque()
    # ``allowed_origins`` is populated from seeds so multi-seed crawls
    # spanning a couple of known hosts still work with same_origin=True.
    allowed_origins: set[tuple[str, str]] = set()

    for seed in seed_urls:
        allowed_origins.add(_origin(seed))
        queue.append((seed, 0))

    # Bind into a local non-Optional name so the type-checker can follow
    # the branch where we own the client.
    owns_client = client is None
    http_client: httpx.AsyncClient = client or httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT,
        headers={"User-Agent": _DEFAULT_UA},
    )

    pages_fetched = 0
    total_bytes = 0

    try:
        while queue:
            if pages_fetched >= max_pages:
                logger.debug("crawler: max_pages=%d reached, stopping", max_pages)
                break
            if total_bytes >= max_total_html_bytes:
                logger.warning(
                    "crawler: byte cap %d hit, stopping (total=%d)",
                    max_total_html_bytes,
                    total_bytes,
                )
                break

            url, depth = queue.popleft()

            # Canonical dedup — must run before origin/prefix checks so that
            # "already seen" always wins over "would have skipped for other
            # reasons". This keeps the seen-set monotone.
            canonical = canonicalize_url(url)
            if canonical in seen_canonical:
                yield CrawledPage(
                    url=canonical, depth=depth, html=None, status="skip_dedup"
                )
                continue
            seen_canonical.add(canonical)

            # Origin gate.
            if same_origin and _origin(canonical) not in allowed_origins:
                yield CrawledPage(
                    url=canonical, depth=depth, html=None, status="skip_origin"
                )
                continue

            # Path-prefix gate (optional, tighter than origin).
            if path_prefix is not None and not urlparse(canonical).path.startswith(
                path_prefix
            ):
                yield CrawledPage(
                    url=canonical, depth=depth, html=None, status="skip_prefix"
                )
                continue

            # Depth gate — strictly-greater, since depth==max_depth is still
            # visited (its links are just not enqueued below).
            if depth > max_depth:
                yield CrawledPage(
                    url=canonical, depth=depth, html=None, status="skip_depth"
                )
                continue

            # robots.txt compliance gate (T2). Runs before the rate-limit
            # wait so a disallowed URL does not burn our 1-req/sec budget.
            if not await is_url_allowed(canonical):
                yield CrawledPage(
                    url=canonical, depth=depth, html=None, status="skip_robots"
                )
                continue

            # Per-domain politeness: ≥ 1s between fetches to the same host.
            await _rate_limit_for_domain(urlparse(canonical).netloc)

            html = await _fetch(http_client, canonical)
            if html is None:
                yield CrawledPage(
                    url=canonical, depth=depth, html=None, status="fetch_fail"
                )
                continue

            pages_fetched += 1
            # ``len(html)`` counts code points, not bytes, but is a safe
            # over-estimate upper bound on real byte weight for ASCII-heavy
            # docs. Encoding to bytes() on every page would double memory.
            total_bytes += len(html.encode("utf-8", errors="ignore"))

            yield CrawledPage(url=canonical, depth=depth, html=html, status="ok")

            # Enqueue children only while below the depth cap.
            if depth < max_depth:
                for link in _extract_links(html, canonical):
                    queue.append((link, depth + 1))
    finally:
        if owns_client:
            await http_client.aclose()
