"""Recursive URL crawler (§14.5 v2.5 T1 — core only).

Exports:
- ``CrawledPage``: NamedTuple yielded per visited URL.
- ``crawl_urls``: async generator that performs BFS with canonical dedup,
  depth/pages/bytes caps, and optional same-origin/path-prefix filters.
- ``canonicalize_url``: stable URL normalizer used for dedup hashing.

No robots.txt, rate-limiting, or DB writes live here — those belong to T2/T3.
"""

from services.crawler.recursive_crawler import (
    CrawledPage,
    canonicalize_url,
    crawl_urls,
)

__all__ = ["CrawledPage", "canonicalize_url", "crawl_urls"]
