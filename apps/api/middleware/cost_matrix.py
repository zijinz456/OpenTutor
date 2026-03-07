"""Endpoint cost matrix for GCRA cost-aware rate limiting.

Inspired by OpenFang's operation cost matrix. Each endpoint has a cost
reflecting its computational expense relative to others.

Cost scale: 0-100 cost units per request.
Budget: configurable (default 500 cost units per minute per IP).
"""

import re

# ── Exact Path Costs ──
# Higher cost = more expensive operation = consumes more of the rate budget

EXACT_COSTS: dict[str, int] = {
    # Health / metadata (free — never rate-limited)
    "/api/health": 0,
    "/docs": 0,
    "/openapi.json": 0,

    # Auth (low cost)
    "/api/auth/login": 5,
    "/api/auth/register": 5,
    "/api/auth/refresh": 2,

    # Data reads (low cost)
    "/api/courses": 2,
    "/api/preferences": 2,
    "/api/goals": 3,
    "/api/notifications": 2,

    # LLM-heavy operations (high cost)
    "/api/chat/": 30,
    "/api/quiz/extract": 50,
    "/api/flashcards/generate": 40,
    "/api/notes/restructure": 35,

    # File upload / scrape (medium cost — I/O bound)
    "/api/content/files": 15,
    "/api/content/url": 20,

    # Evaluation (high cost — involves LLM)
    "/api/eval/regression": 100,
}

# ── Prefix-Based Costs (for parameterised routes) ──
# Checked in order; first match wins.

PREFIX_COSTS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^/api/chat/?$"), 30),
    (re.compile(r"^/api/courses/[^/]+/chat"), 30),
    (re.compile(r"^/api/courses/[^/]+"), 3),
    (re.compile(r"^/api/progress"), 3),
    (re.compile(r"^/api/wrong-answers"), 3),
    (re.compile(r"^/api/tasks"), 5),
    (re.compile(r"^/api/voice"), 30),
    (re.compile(r"^/api/notifications/push"), 2),
    (re.compile(r"^/api/experiments"), 10),
    (re.compile(r"^/api/usage"), 2),
]

DEFAULT_COST = 5

# Write methods are inherently more expensive (DB writes, side-effects).
WRITE_MULTIPLIER = 1.5
WRITE_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def get_endpoint_cost(path: str, method: str = "GET") -> int:
    """Look up the cost for a given endpoint path and HTTP method.

    Resolution order:
      1. Exact match (O(1) dict lookup)
      2. Prefix regex match (O(n), small n)
      3. Default fallback

    POST/PUT/DELETE/PATCH operations get a 1.5× multiplier (rounded up).
    """
    # 1. Exact match
    cost = EXACT_COSTS.get(path)

    # 2. Prefix match
    if cost is None:
        for pattern, prefix_cost in PREFIX_COSTS:
            if pattern.match(path):
                cost = prefix_cost
                break

    # 3. Default
    if cost is None:
        cost = DEFAULT_COST

    # Write-method multiplier
    if method in WRITE_METHODS and cost > 0:
        cost = int(cost * WRITE_MULTIPLIER + 0.5)  # round up

    return cost
