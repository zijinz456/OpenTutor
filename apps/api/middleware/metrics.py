"""In-process metrics collection middleware.

Tracks:
- Request count by method, path, status
- Request latency histogram (p50, p90, p95, p99)
- Error rate by endpoint
- LLM call count and token usage (via external registration)
- Application uptime

Exposes metrics via get_metrics() for the health endpoint.
No external dependencies (Prometheus/StatsD) required.
"""

from __future__ import annotations

import bisect
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

_start_time = time.monotonic()


# ── Histogram (lock-free, approximate) ──

@dataclass
class _Histogram:
    """Simple sorted-insert histogram for latency percentiles."""
    values: list[float] = field(default_factory=list)
    max_samples: int = 10_000

    def record(self, value: float) -> None:
        if len(self.values) >= self.max_samples:
            # Downsample: keep every other value
            self.values = self.values[::2]
        bisect.insort(self.values, value)

    def percentile(self, p: float) -> float:
        if not self.values:
            return 0.0
        idx = int(len(self.values) * p / 100)
        return self.values[min(idx, len(self.values) - 1)]

    def count(self) -> int:
        return len(self.values)


# ── Global metrics store ──

@dataclass
class _MetricsStore:
    request_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    error_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    latency: dict[str, _Histogram] = field(default_factory=lambda: defaultdict(_Histogram))
    # LLM metrics (registered externally)
    llm_call_count: int = 0
    llm_total_tokens: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_latency: _Histogram = field(default_factory=_Histogram)


_store = _MetricsStore()


def _normalize_path(path: str) -> str:
    """Normalize path by replacing UUIDs and numeric IDs with placeholders."""
    import re
    # Replace UUIDs
    path = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "{id}",
        path,
    )
    # Replace numeric IDs in path segments
    path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
    return path


# ── Public API for LLM metrics ──

def record_llm_call(
    *,
    duration_ms: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """Record an LLM API call. Called from the LLM router."""
    _store.llm_call_count += 1
    _store.llm_prompt_tokens += prompt_tokens
    _store.llm_completion_tokens += completion_tokens
    _store.llm_total_tokens += prompt_tokens + completion_tokens
    _store.llm_latency.record(duration_ms)


def get_metrics() -> dict[str, Any]:
    """Return current metrics snapshot for the health endpoint."""
    uptime_seconds = time.monotonic() - _start_time

    # Aggregate latency across all endpoints
    all_latencies = _Histogram()
    total_requests = 0
    total_errors = 0
    for key, hist in _store.latency.items():
        for v in hist.values:
            all_latencies.record(v)
    for count in _store.request_count.values():
        total_requests += count
    for count in _store.error_count.values():
        total_errors += count

    # Per-endpoint breakdown (top 20 by request count)
    endpoint_stats = []
    for key, count in sorted(_store.request_count.items(), key=lambda x: -x[1])[:20]:
        hist = _store.latency.get(key, _Histogram())
        errors = _store.error_count.get(key, 0)
        endpoint_stats.append({
            "endpoint": key,
            "requests": count,
            "errors": errors,
            "p50_ms": round(hist.percentile(50), 1),
            "p95_ms": round(hist.percentile(95), 1),
            "p99_ms": round(hist.percentile(99), 1),
        })

    return {
        "uptime_seconds": round(uptime_seconds, 1),
        "total_requests": total_requests,
        "total_errors": total_errors,
        "error_rate": round(total_errors / max(total_requests, 1), 4),
        "latency": {
            "p50_ms": round(all_latencies.percentile(50), 1),
            "p90_ms": round(all_latencies.percentile(90), 1),
            "p95_ms": round(all_latencies.percentile(95), 1),
            "p99_ms": round(all_latencies.percentile(99), 1),
        },
        "llm": {
            "calls": _store.llm_call_count,
            "total_tokens": _store.llm_total_tokens,
            "prompt_tokens": _store.llm_prompt_tokens,
            "completion_tokens": _store.llm_completion_tokens,
            "p50_ms": round(_store.llm_latency.percentile(50), 1),
            "p95_ms": round(_store.llm_latency.percentile(95), 1),
        },
        "endpoints": endpoint_stats,
    }


# ── Middleware ──

class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect per-request metrics (count, latency, errors)."""

    _SKIP_PATHS = {"/docs", "/openapi.json", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self._SKIP_PATHS:
            return await call_next(request)

        normalized = _normalize_path(path)
        key = f"{request.method} {normalized}"

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        _store.request_count[key] += 1
        _store.latency[key].record(duration_ms)

        if response.status_code >= 400:
            _store.error_count[key] += 1

        if duration_ms > 500:
            logger.warning("Slow request: %s %.0fms status=%d", key, duration_ms, response.status_code)

        return response
