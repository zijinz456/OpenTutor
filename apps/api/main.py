"""OpenTutor Zenus API — FastAPI entry point."""

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy.exc import SQLAlchemyError

from config import settings
from libs.exceptions import AppError, LLMUnavailableError, is_llm_unavailable_error
from libs.logging_setup import configure_logging
from services.app_lifecycle import lifespan
from services.llm.router import LLMConfigurationError
from services.router_registry import register_routers


def _datetime_serializer(dt: datetime) -> str:
    """Ensure all datetimes are serialized with UTC timezone (ISO 8601).

    SQLite returns naive datetimes; this guarantees RFC 3339 compliance.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# Initialize structured logging (structlog + stdlib integration)
configure_logging()
logger = logging.getLogger(__name__)


def _configure_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "Accept",
            "Origin",
            "X-Requested-With",
            "X-CSRF-Token",
        ],
    )

    # Observability middleware (innermost — runs closest to handler)
    from middleware.metrics import MetricsMiddleware
    from middleware.tracing import TracingMiddleware

    app.add_middleware(MetricsMiddleware)
    app.add_middleware(TracingMiddleware)

    # Security middleware stack (order matters: outermost runs first)
    from middleware.security import SecurityHeadersMiddleware, RateLimitMiddleware, AuditLogMiddleware

    app.add_middleware(AuditLogMiddleware)
    app.add_middleware(
        RateLimitMiddleware,
        default_rpm=120,
        llm_rpm=20,
        cost_budget_per_minute=settings.rate_limit_cost_budget,
        cost_aware=(settings.rate_limit_mode == "cost_aware"),
    )
    app.add_middleware(SecurityHeadersMiddleware)

    # CSRF protection (outermost security layer)
    if settings.environment == "production" or settings.auth_enabled:
        from middleware.csrf import CSRFMiddleware
        app.add_middleware(CSRFMiddleware)


async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status, content=exc.to_dict())


async def llm_configuration_error_handler(_: Request, exc: LLMConfigurationError):
    return JSONResponse(status_code=503, content={"code": "llm_configuration_error", "message": str(exc), "status": 503})


async def database_error_handler(_: Request, exc: SQLAlchemyError):
    logger.error("Database error: %s", exc, exc_info=True)
    return JSONResponse(status_code=503, content={"code": "database_error", "message": "Service temporarily unavailable", "status": 503})


async def generic_error_handler(_: Request, exc: Exception):
    if is_llm_unavailable_error(exc):
        llm_error = LLMUnavailableError(str(exc))
        return JSONResponse(status_code=llm_error.status, content=llm_error.to_dict())
    # Catch LLM provider connection errors that weren't caught in handlers
    exc_module = getattr(type(exc), "__module__", "")
    if "openai" in exc_module or "anthropic" in exc_module:
        logger.warning("LLM provider error: %s", exc, exc_info=True)
        return JSONResponse(status_code=503, content={"code": "llm_unavailable", "message": "LLM service temporarily unavailable", "status": 503})
    # Catch Playwright errors that weren't caught in handlers
    if "playwright" in exc_module:
        logger.warning("Playwright error: %s", exc, exc_info=True)
        return JSONResponse(status_code=502, content={"code": "browser_error", "message": "Browser automation failed", "status": 502})
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"code": "internal_error", "message": "An unexpected error occurred", "status": 500})


def _register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(LLMConfigurationError, llm_configuration_error_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)


_COMMON_ERROR_RESPONSES = {
    401: {"description": "Not authenticated"},
    403: {"description": "Permission denied"},
    404: {"description": "Resource not found"},
    500: {"description": "Internal server error"},
    502: {"description": "Browser automation / upstream error"},
    503: {"description": "Service unavailable (DB or LLM)"},
}


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenTutor Zenus API",
        description="Personalized Learning Agent Backend",
        version="0.1.0",
        lifespan=lifespan,
        responses=_COMMON_ERROR_RESPONSES,
    )
    _configure_middleware(app)
    _register_exception_handlers(app)
    register_routers(app)
    return app


app = create_app()
