"""CSRF protection middleware.

Generates a per-session CSRF token and validates it on state-mutating requests.
The token is sent via a non-HttpOnly cookie (`csrf_token`) so the frontend can
read it and include it in the `X-CSRF-Token` header.

Exempt paths: health checks, webhooks, OpenAPI docs.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from config import settings

logger = logging.getLogger(__name__)

# Token validity: 24 hours
_TOKEN_MAX_AGE = 86400
_COOKIE_NAME = "csrf_token"
_HEADER_NAME = "x-csrf-token"

_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_EXEMPT_PREFIXES = (
    "/api/health",
    "/api/webhooks/",
    "/docs",
    "/openapi.json",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
)


def _generate_token() -> str:
    """Generate a CSRF token: timestamp.random.hmac."""
    timestamp = str(int(time.time()))
    random_part = secrets.token_hex(16)
    payload = f"{timestamp}.{random_part}"
    sig = hmac.new(
        settings.jwt_secret_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f"{payload}.{sig}"


def _validate_token(token: str) -> bool:
    """Validate a CSRF token's signature and age."""
    parts = token.split(".")
    if len(parts) != 3:
        return False

    timestamp_str, random_part, sig = parts

    # Check signature
    payload = f"{timestamp_str}.{random_part}"
    expected_sig = hmac.new(
        settings.jwt_secret_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]

    if not hmac.compare_digest(sig, expected_sig):
        return False

    # Check age
    try:
        token_time = int(timestamp_str)
    except ValueError:
        return False

    if time.time() - token_time > _TOKEN_MAX_AGE:
        return False

    return True


class CSRFMiddleware(BaseHTTPMiddleware):
    """Validate CSRF tokens on state-mutating requests.

    Flow:
    1. On any response, if no csrf_token cookie exists, set one.
    2. On mutating requests (POST/PUT/PATCH/DELETE), require the token
       in the X-CSRF-Token header matching the cookie.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip exempt paths
        if any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return await call_next(request)

        method = request.method

        # Validate CSRF on mutating requests
        if method in _MUTATING_METHODS:
            cookie_token = request.cookies.get(_COOKIE_NAME, "")
            header_token = request.headers.get(_HEADER_NAME, "")

            if not cookie_token or not header_token:
                logger.warning(
                    "SECURITY | CSRF_MISSING | path=%s | method=%s | cookie=%s | header=%s",
                    path, method, bool(cookie_token), bool(header_token),
                )
                return Response(
                    content='{"code":"csrf_error","message":"CSRF token missing","status":403}',
                    status_code=403,
                    media_type="application/json",
                )

            if not hmac.compare_digest(cookie_token, header_token):
                logger.warning("SECURITY | CSRF_MISMATCH | path=%s | method=%s", path, method)
                return Response(
                    content='{"code":"csrf_error","message":"CSRF token mismatch","status":403}',
                    status_code=403,
                    media_type="application/json",
                )

            if not _validate_token(cookie_token):
                logger.warning("SECURITY | CSRF_INVALID | path=%s | method=%s", path, method)
                return Response(
                    content='{"code":"csrf_error","message":"CSRF token invalid or expired","status":403}',
                    status_code=403,
                    media_type="application/json",
                )

        response = await call_next(request)

        # Set CSRF cookie if not present
        if _COOKIE_NAME not in request.cookies:
            token = _generate_token()
            response.set_cookie(
                key=_COOKIE_NAME,
                value=token,
                max_age=_TOKEN_MAX_AGE,
                httponly=False,  # Frontend needs to read this
                samesite="strict",
                secure=settings.environment != "development",
                path="/",
            )

        return response
