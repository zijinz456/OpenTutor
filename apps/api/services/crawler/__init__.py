"""Recursive URL crawler (§14.5 v2.5 T1+T2).

Exports:
- ``CrawledPage``: NamedTuple yielded per visited URL.
- ``crawl_urls``: async generator that performs BFS with canonical dedup,
  depth/pages/bytes caps, optional same-origin/path-prefix filters,
  robots.txt gating (T2), and per-domain rate limiting (T2).
- ``canonicalize_url``: stable URL normalizer used for dedup hashing.
- ``is_url_allowed``: robots.txt compliance check (fail-closed, TTL-cached).

DB writes and router wiring belong to T3.
"""

from services.crawler.recursive_crawler import (
    CrawledPage,
    canonicalize_url,
    crawl_urls,
)
from services.crawler.robots import is_url_allowed

__all__ = ["CrawledPage", "canonicalize_url", "crawl_urls", "is_url_allowed"]
