"""Security middleware: headers, rate limiting, audit logging, prompt injection guard.

Adds:
1. Security headers (CSP, HSTS, X-Frame-Options, etc.)
2. Rate limiting (per-IP, sliding window)
3. Audit logging (who accessed what, when)
4. Prompt injection detection (pattern-based pre-filter)
"""

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


# ── Security Headers ──

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
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
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ── Rate Limiting ──

@dataclass
class _RateBucket:
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiter per client IP.

    Default: 60 requests per minute for general endpoints,
    10 requests per minute for LLM-heavy endpoints (/chat, /quiz/generate).
    """

    def __init__(self, app, default_rpm: int = 60, llm_rpm: int = 10):
        super().__init__(app)
        self.default_rpm = default_rpm
        self.llm_rpm = llm_rpm
        self._buckets: dict[str, _RateBucket] = defaultdict(_RateBucket)

    # LLM-heavy endpoints that need stricter limits
    _LLM_PATHS = {"/api/chat/stream", "/api/quiz/generate", "/api/flashcards/generate"}

    def _get_client_ip(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _check_rate(self, key: str, rpm: int) -> bool:
        """Token bucket algorithm. Returns True if request is allowed."""
        bucket = self._buckets[key]
        now = time.monotonic()
        elapsed = now - bucket.last_refill
        bucket.last_refill = now

        # Refill tokens (1 token per second * rpm/60)
        refill_rate = rpm / 60.0
        bucket.tokens = min(rpm, bucket.tokens + elapsed * refill_rate)

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    async def dispatch(self, request: Request, call_next):
        client_ip = self._get_client_ip(request)
        path = request.url.path

        # Determine rate limit
        is_llm = any(path.startswith(p) for p in self._LLM_PATHS)
        rpm = self.llm_rpm if is_llm else self.default_rpm
        key = f"{client_ip}:{'llm' if is_llm else 'general'}"

        if not self._check_rate(key, rpm):
            logger.warning("Rate limited: %s on %s", client_ip, path)
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

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self._SKIP_PATHS:
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not client_ip and request.client:
            client_ip = request.client.host

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


def detect_prompt_injection(text: str) -> bool:
    """Check if text contains common prompt injection patterns.

    Returns True if injection detected.
    This is a pre-filter — not a replacement for proper sandboxing.
    """
    for pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return True
    return False


def sanitize_user_input(text: str) -> str:
    """Sanitize user input by stripping control characters and limiting length.

    Does NOT strip injection patterns (detection is separate).
    """
    # Remove null bytes and control characters (except newlines/tabs)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    # Limit to 10K characters
    return cleaned[:10000]
