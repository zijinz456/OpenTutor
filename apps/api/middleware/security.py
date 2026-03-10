"""Security middleware: headers, rate limiting, audit logging, prompt injection guard.

Adds:
1. Security headers (CSP, HSTS, X-Frame-Options, etc.)
2. Rate limiting (per-IP, sliding window — simple or GCRA cost-aware)
3. Audit logging (who accessed what, when)
4. Prompt injection detection (pattern-based pre-filter)
"""

import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings

logger = logging.getLogger(__name__)

# ── Constants ──

HSTS_MAX_AGE = 31_536_000  # 1 year in seconds
STALE_BUCKET_SECONDS = 120.0  # evict rate-limit buckets after 2 min inactivity
MAX_USER_INPUT_LENGTH = 10_000


def _extract_client_ip(request: Request) -> str:
    """Resolve client IP consistently across security middleware."""
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Security Headers ──

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self' http://localhost:* ws://localhost:*; "
        "frame-ancestors 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        # HSTS only in production
        if not request.url.hostname or request.url.hostname != "localhost":
            response.headers["Strict-Transport-Security"] = f"max-age={HSTS_MAX_AGE}; includeSubDomains"
        return response


# ── Rate Limiting ──

@dataclass
class _RateBucket:
    tokens: float = -1.0  # sentinel: initialised on first use
    last_refill: float = field(default_factory=time.monotonic)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiter per client IP.

    Two modes (controlled by ``cost_aware`` flag):

    **Simple mode** (default, backward-compatible):
      60 RPM for general endpoints, 10 RPM for LLM-heavy endpoints.

    **Cost-aware GCRA mode** (inspired by OpenFang):
      Each endpoint has a cost (0-100). Budget is ``cost_budget_per_minute``
      cost units per IP per minute. Health checks cost 0 (exempt), data
      reads cost 2-3, LLM calls cost 30-50.
    """

    _LLM_PATHS = {"/api/chat", "/api/quiz/extract", "/api/flashcards/generate"}
    _EXEMPT_PREFIXES = ("/api/webhooks/", "/api/health", "/docs", "/openapi.json")

    def __init__(
        self,
        app,
        default_rpm: int = 60,
        llm_rpm: int = 10,
        cost_budget_per_minute: int = 500,
        cost_aware: bool = False,
    ):
        super().__init__(app)
        # Simple mode
        self.default_rpm = default_rpm
        self.llm_rpm = llm_rpm
        # Cost-aware mode
        self.cost_budget = cost_budget_per_minute
        self.cost_aware = cost_aware
        self._buckets: dict[str, _RateBucket] = defaultdict(_RateBucket)
        self._last_cleanup: float = time.monotonic()
        self._max_buckets: int = 10000
        self._cleanup_interval: float = 300.0  # 5 minutes

    def _get_client_ip(self, request: Request) -> str:
        return _extract_client_ip(request)

    def _get_rate_key(self, request: Request, suffix: str) -> str:
        """Build rate limit key: per-user when authenticated, else per-IP."""
        user_id = getattr(request.state, "user_id", None) if hasattr(request, "state") else None
        if user_id:
            return f"user:{user_id}:{suffix}"
        return f"ip:{self._get_client_ip(request)}:{suffix}"

    def _maybe_cleanup_buckets(self) -> None:
        """Evict stale rate limit buckets to prevent unbounded memory growth."""
        now = time.monotonic()
        bucket_count = len(self._buckets)

        # Force eviction when bucket count exceeds max, regardless of interval
        if bucket_count > self._max_buckets or now - self._last_cleanup >= self._cleanup_interval:
            self._last_cleanup = now
            stale_threshold = STALE_BUCKET_SECONDS
            stale_keys = [k for k, b in self._buckets.items() if now - b.last_refill > stale_threshold]
            for k in stale_keys:
                del self._buckets[k]
            # If still over limit after stale eviction, evict oldest buckets
            if len(self._buckets) > self._max_buckets:
                sorted_keys = sorted(self._buckets.keys(), key=lambda k: self._buckets[k].last_refill)
                excess = len(self._buckets) - self._max_buckets
                for k in sorted_keys[:excess]:
                    del self._buckets[k]
                logger.warning("Rate limiter: force-evicted %d buckets (was over max %d)", excess, self._max_buckets)
            elif stale_keys:
                logger.debug("Rate limiter: evicted %d stale buckets (%d remaining)", len(stale_keys), len(self._buckets))

    # ── Simple mode ──

    def _check_simple_rate(self, key: str, rpm: int) -> bool:
        """Original token bucket algorithm. Returns True if allowed."""
        bucket = self._buckets[key]
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.last_refill = now

        if bucket.tokens < 0:
            bucket.tokens = float(rpm)

        refill_rate = rpm / 60.0
        bucket.tokens = min(rpm, bucket.tokens + elapsed * refill_rate)

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    # ── Cost-aware GCRA mode ──

    def _check_cost_rate(self, key: str, cost: int) -> tuple[bool, float]:
        """Cost-weighted token bucket. Returns (allowed, retry_after_seconds)."""
        bucket = self._buckets[key]
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.last_refill = now

        if bucket.tokens < 0:
            bucket.tokens = float(self.cost_budget)

        refill_rate = self.cost_budget / 60.0
        bucket.tokens = min(self.cost_budget, bucket.tokens + elapsed * refill_rate)

        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return True, 0.0

        deficit = cost - bucket.tokens
        retry_after = deficit / refill_rate if refill_rate > 0 else 60.0
        return False, retry_after

    # ── Dispatch ──

    async def dispatch(self, request: Request, call_next):
        if os.environ.get("DISABLE_RATE_LIMIT") == "1":
            return await call_next(request)

        path = request.url.path

        # Exempt paths
        if any(path.startswith(prefix) for prefix in self._EXEMPT_PREFIXES):
            return await call_next(request)

        client_ip = self._get_client_ip(request)
        self._maybe_cleanup_buckets()

        if self.cost_aware:
            from middleware.cost_matrix import get_endpoint_cost

            cost = get_endpoint_cost(path, request.method)
            if cost == 0:
                return await call_next(request)

            key = self._get_rate_key(request, "cost")
            allowed, retry_after = self._check_cost_rate(key, cost)

            if not allowed:
                logger.warning(
                    "Rate limited (cost-aware): %s on %s (cost=%d, retry=%.1fs)",
                    client_ip, path, cost, retry_after,
                )
                return Response(
                    content=json.dumps({
                        "detail": "Rate limit exceeded. Please slow down.",
                        "cost": cost,
                        "retry_after": round(retry_after, 1),
                    }),
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(max(1, int(retry_after)))},
                )
        else:
            # Simple mode (backward-compatible)
            is_llm = any(path.startswith(p) for p in self._LLM_PATHS)
            rpm = self.llm_rpm if is_llm else self.default_rpm
            key = self._get_rate_key(request, "llm" if is_llm else "general")

            if not self._check_simple_rate(key, rpm):
                logger.warning("SECURITY | RATE_LIMIT | ip=%s | path=%s | mode=simple | rpm=%d", client_ip, path, rpm)
                return Response(
                    content='{"detail":"Rate limit exceeded. Please slow down."}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": "10"},
                )

        return await call_next(request)


# ── Audit Logging ──

class AuditLogMiddleware(BaseHTTPMiddleware):
    """Log API access for security auditing.

    Logs: timestamp, client IP, method, path, status code, latency.
    Skips health checks and static assets.
    """

    _SKIP_PATHS = {"/api/health", "/docs", "/openapi.json", "/favicon.ico"}
    _MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self._SKIP_PATHS:
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        client_ip = _extract_client_ip(request)

        logger.info(
            "AUDIT | %s %s | status=%d | ip=%s | %.0fms",
            request.method, path, response.status_code, client_ip, duration_ms,
        )
        return response


# ── Prompt Injection Guard ──

# Common injection patterns (case-insensitive)
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"ignore\s+(all\s+)?above\s+instructions",
    r"disregard\s+(all\s+)?previous",
    r"you\s+are\s+now\s+(?:a|an)\s+(?:different|new)\s+(?:ai|assistant|bot)",
    r"system\s*:\s*you\s+are",
    r"<\|im_start\|>",
    r"\[\[system\]\]",
    r"```\s*system",
    r"reveal\s+(?:your|the)\s+system\s+prompt",
    r"show\s+(?:me\s+)?(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)",
    r"print\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)",
    r"output\s+(?:your|the)\s+(?:system\s+)?(?:prompt|instructions)",
    r"what\s+(?:is|are)\s+your\s+(?:system\s+)?(?:prompt|instructions)",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _INJECTION_PATTERNS]


def detect_prompt_injection(text: str, client_ip: str = "unknown") -> bool:
    """Check if text contains common prompt injection patterns.

    Returns True if injection detected.
    This is a best-effort pre-filter — not a replacement for proper sandboxing.
    """
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            logger.warning(
                "SECURITY | PROMPT_INJECTION | ip=%s | pattern=%s | input_preview=%.100s",
                client_ip, pattern.pattern, text,
            )
            return True
    return False


def sanitize_user_input(text: str) -> str:
    """Sanitize user input by stripping control characters and limiting length.

    Does NOT strip injection patterns (detection is separate).
    """
    # Remove null bytes and control characters (except newlines/tabs)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return cleaned[:MAX_USER_INPUT_LENGTH]
