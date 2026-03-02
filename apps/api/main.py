"""OpenTutor Zenus API — FastAPI entry point."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy.exc import SQLAlchemyError

from config import settings
from libs.exceptions import AppError, LLMUnavailableError, is_llm_unavailable_error
from services.app_lifecycle import lifespan
from services.llm.router import LLMConfigurationError
from services.router_registry import register_routers

logger = logging.getLogger(__name__)


def _configure_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"code": "internal_error", "message": "An unexpected error occurred", "status": 500})


def _register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(LLMConfigurationError, llm_configuration_error_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
    app.add_exception_handler(Exception, generic_error_handler)


def _mount_mcp(app: FastAPI) -> None:
    """Mount MCP servers for external AI agent access.

    1. FastApiMCP at ``/mcp`` — auto-exposes all FastAPI routes.
    2. Education MCP at ``/mcp/education`` — curated high-level learning tools.
    """
    # 1. Auto-expose all routes
    try:
        from fastapi_mcp import FastApiMCP

        mcp_server = FastApiMCP(
            app,
            name="OpenTutor Agent",
            description="Personal Learning Agent — education tools accessible via MCP",
        )
        mcp_server.mount()
        logger.info("FastApiMCP mounted at /mcp (all routes exposed)")
    except Exception as exc:
        logger.warning("FastApiMCP mount failed: %s", exc)

    # 2. Curated education tools
    try:
        from services.mcp.server import mount_education_mcp

        mount_education_mcp(app)
    except Exception as exc:
        logger.warning("Education MCP mount failed: %s", exc)


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenTutor Zenus API",
        description="Personalized Learning Agent Backend",
        version="0.1.0",
        lifespan=lifespan,
    )
    _configure_middleware(app)
    _register_exception_handlers(app)
    register_routers(app)
    _mount_mcp(app)
    return app


app = create_app()
