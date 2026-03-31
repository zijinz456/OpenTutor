"""Request tracing middleware using OpenTelemetry.

Provides:
1. Automatic request_id generation and propagation via context vars.
2. OpenTelemetry span creation per request (when OTel is available).
3. Span attributes: user_id, course_id, method, path, status_code.

OTel is optional — if not installed, only request_id context is set.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from libs.logging_setup import (
    course_id_var,
    generate_request_id,
    request_id_var,
    user_id_var,
)

logger = logging.getLogger(__name__)

# ── OpenTelemetry (optional) ──

_tracer = None

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create({"service.name": "opentutor-api"})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("opentutor.api")
    logger.info("OpenTelemetry tracing initialized")
except ImportError:
    logger.debug("OpenTelemetry not installed — tracing disabled (request_id still active)")


def _extract_user_id(request: Request) -> str:
    """Extract user_id from request state (set by auth dependency)."""
    return getattr(request.state, "user_id", "") or ""


def _extract_course_id(request: Request) -> str:
    """Extract course_id from path parameters."""
    path_params = request.path_params
    return str(path_params.get("course_id", "")) or ""


class TracingMiddleware(BaseHTTPMiddleware):
    """Generate request_id and optionally create OTel spans."""

    _SKIP_PATHS = {"/api/health", "/docs", "/openapi.json", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self._SKIP_PATHS:
            return await call_next(request)

        # Generate and bind request_id
        rid = generate_request_id()
        request_id_var.set(rid)

        # Bind user/course context (may be empty at this point)
        uid = _extract_user_id(request)
        cid = _extract_course_id(request)
        user_id_var.set(uid)
        course_id_var.set(cid)

        # Set request_id on response header for client-side correlation
        start = time.monotonic()

        if _tracer is not None:
            with _tracer.start_as_current_span(
                f"{request.method} {path}",
                attributes={
                    "http.method": request.method,
                    "http.url": str(request.url),
                    "http.route": path,
                    "request.id": rid,
                },
            ) as span:
                response = await call_next(request)
                duration_ms = (time.monotonic() - start) * 1000
                span.set_attribute("http.status_code", response.status_code)
                span.set_attribute("http.duration_ms", round(duration_ms, 1))
                if uid:
                    span.set_attribute("user.id", uid)
                if cid:
                    span.set_attribute("course.id", cid)
        else:
            response = await call_next(request)
            duration_ms = (time.monotonic() - start) * 1000

        response.headers["X-Request-ID"] = rid
        response.headers["X-Response-Time"] = f"{duration_ms:.0f}ms"

        return response
