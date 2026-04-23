"""robots.txt compliance gate for the recursive crawler (§14.5 v2.5 T2).

One public coroutine: :func:`is_url_allowed`. Semantics:

* Per-domain TTL cache (1h) of ``RobotFileParser`` instances. Second call
  on the same domain never re-fetches ``/robots.txt``.
* **Fail-closed on fetch error** (critic concern #6 in v2.5 plan). If
  ``/robots.txt`` is unreachable, returns 500, times out, or the parser
  raises — we treat the domain as fully disallowed and cache ``None``
  against the origin key for the same TTL. Better to skip a page than to
  ship a crawler that silently ignores sites that were temporarily
  unreachable when we first checked them.

The stdlib ``urllib.robotparser`` is synchronous. That is acceptable here
because robots.txt fetches are sub-second, happen once per domain per hour,
and running them on the default executor would complicate the fail-closed
caching contract for no measurable benefit on a personal-tool crawler.
"""

from __future__ import annotations

import logging
import urllib.robotparser
from urllib.parse import urlparse

from cachetools import TTLCache

logger = logging.getLogger(__name__)

# One hour TTL matches the architect's plan and the common robots.txt
# refresh cadence. ``maxsize=64`` covers comfortably more than any realistic
# crawl fan-out (same-origin default + optional allowlist).
_ROBOTS_CACHE: TTLCache[str, urllib.robotparser.RobotFileParser | None] = TTLCache(
    maxsize=64, ttl=3600
)

# Identifiable UA for robots.txt compliance. The T1 crawler uses a similar
# UA for actual HTTP fetches; we keep the robots check consistent so that
# ``User-agent:`` directives matching either string behave predictably.
DEFAULT_USER_AGENT = "LearnDopamineBot/1.0"


async def is_url_allowed(url: str, user_agent: str = DEFAULT_USER_AGENT) -> bool:
    """Return True iff the URL's domain's ``robots.txt`` permits ``user_agent``.

    Fail-closed: any error fetching or parsing ``robots.txt`` is treated as
    disallow. The failure is cached against the origin so a flaky host does
    not cause repeated fetches for every URL on that host.
    """
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if base in _ROBOTS_CACHE:
        cached = _ROBOTS_CACHE[base]
        if cached is None:
            # Prior fetch failed within the TTL window — stay fail-closed.
            return False
        return cached.can_fetch(user_agent, url)

    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(f"{base}/robots.txt")
    try:
        # ``.read()`` is synchronous stdlib urllib. Sub-second in practice;
        # we accept the blocking call rather than wrapping in run_in_executor
        # because (a) it runs at most once per domain per hour, (b) making
        # it async would complicate the fail-closed caching invariant.
        parser.read()
    except Exception as exc:  # noqa: BLE001 — fail-closed swallows everything
        logger.debug("robots.txt fetch failed for %s: %s", base, exc)
        _ROBOTS_CACHE[base] = None
        return False

    _ROBOTS_CACHE[base] = parser
    return parser.can_fetch(user_agent, url)
