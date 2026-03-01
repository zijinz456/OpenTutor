"""OpenTutor Zenus API — FastAPI entry point."""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database import engine
from libs.exceptions import AppError
from routers import auth, upload, chat, courses, preferences, quiz, notes, workflows, progress, flashcards, canvas, notifications, scrape, scenes, wrong_answers, tasks, goals, evaluation, experiments, push, notification_settings
from services.llm.router import LLMConfigurationError

logger = logging.getLogger(__name__)


async def _maybe_seed_system_data() -> None:
    if not settings.app_auto_seed_system:
        return

    from database import async_session
    from services.templates.system import seed_builtin_templates
    from services.scene.seed import seed_preset_scenes

    async with async_session() as db:
        await seed_builtin_templates(db)
        await seed_preset_scenes(db)
        await db.commit()
    logger.info("Seeded built-in templates and preset scenes")


def _maybe_start_scheduler() -> None:
    if not settings.app_run_scheduler:
        return
    from services.scheduler.engine import start_scheduler

    start_scheduler()
    logger.info("Scheduler started")


def _maybe_stop_scheduler() -> None:
    if not settings.app_run_scheduler:
        return
    from services.scheduler.engine import stop_scheduler

    stop_scheduler()
    logger.info("Scheduler stopped")


def _should_run_activity_engine() -> bool:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return settings.app_run_activity_engine


def _maybe_start_activity_engine() -> None:
    if not _should_run_activity_engine():
        return
    from services.activity.engine import start_activity_engine

    start_activity_engine()
    logger.info("Activity engine started")


async def _maybe_stop_activity_engine() -> None:
    if not _should_run_activity_engine():
        return
    from services.activity.engine import stop_activity_engine

    await stop_activity_engine()
    logger.info("Activity engine stopped")


async def _maybe_connect_mcp_servers() -> None:
    """Connect to MCP servers and register their tools."""
    try:
        from services.agent.tools.mcp_client import load_mcp_tools

        count = await load_mcp_tools()
        if count:
            logger.info("Registered %d MCP tools", count)
    except Exception as e:
        logger.warning("MCP server connection failed: %s", e)


async def _maybe_disconnect_mcp_servers() -> None:
    """Shut down MCP server connections."""
    try:
        from services.agent.tools.mcp_client import shutdown_mcp_providers

        await shutdown_mcp_providers()
    except Exception as e:
        logger.debug("MCP disconnect: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create upload directory
    os.makedirs(settings.upload_dir, exist_ok=True)
    from services.agent.orchestrator import wait_for_background_tasks

    await _maybe_seed_system_data()
    await _maybe_connect_mcp_servers()
    _maybe_start_scheduler()
    _maybe_start_activity_engine()
    yield
    await _maybe_stop_activity_engine()
    _maybe_stop_scheduler()           # Stop scheduling new tasks first
    await wait_for_background_tasks() # Then wait for in-flight tasks
    await _maybe_disconnect_mcp_servers()
    await engine.dispose()


app = FastAPI(
    title="OpenTutor Zenus API",
    description="Personalized Learning Agent Backend",
    version="0.1.0",
    lifespan=lifespan,
)

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
app.add_middleware(RateLimitMiddleware, default_rpm=120, llm_rpm=20)
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status, content=exc.to_dict())


@app.exception_handler(LLMConfigurationError)
async def llm_configuration_error_handler(_: Request, exc: LLMConfigurationError):
    return JSONResponse(status_code=503, content={"code": "llm_configuration_error", "message": str(exc), "status": 503})

# Auth endpoints only available when AUTH_ENABLED=true (production mode)
if settings.auth_enabled:
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(upload.router, prefix="/api/content", tags=["content"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(courses.router, prefix="/api/courses", tags=["courses"])
app.include_router(preferences.router, prefix="/api/preferences", tags=["preferences"])
app.include_router(quiz.router, prefix="/api/quiz", tags=["quiz"])
app.include_router(notes.router, prefix="/api/notes", tags=["notes"])
app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
app.include_router(progress.router, prefix="/api/progress", tags=["progress"])
app.include_router(flashcards.router, prefix="/api/flashcards", tags=["flashcards"])
app.include_router(canvas.router, prefix="/api/canvas", tags=["canvas"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(scrape.router, prefix="/api/scrape", tags=["scrape"])
app.include_router(scenes.router, prefix="/api/scenes", tags=["scenes"])
app.include_router(wrong_answers.router, prefix="/api/wrong-answers", tags=["wrong-answers"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(goals.router, prefix="/api/goals", tags=["goals"])
app.include_router(evaluation.router, prefix="/api/eval", tags=["evaluation"])
app.include_router(experiments.router, prefix="/api/experiments", tags=["experiments"])
app.include_router(push.router, prefix="/api/notifications/push", tags=["notifications"])
app.include_router(notification_settings.router, prefix="/api/notifications", tags=["notifications"])

# Multi-channel webhook endpoints (only if channels configured)
if settings.enabled_channels:
    from routers import webhooks
    app.include_router(webhooks.router, prefix="/api/webhooks", tags=["webhooks"])


@app.get("/api/health")
async def health():
    from sqlalchemy import text
    from database import async_session
    from services.llm.router import get_registry
    from services.agent.container_sandbox import container_runtime_available

    # Database connectivity check
    db_ok = False
    try:
        async with async_session() as db:
            await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        logger.warning("Health check: database unreachable")

    registry = get_registry()
    provider_health = {
        name: client.is_healthy
        for name, client in registry._providers.items()
    }
    if not registry.available_providers:
        llm_status = "configuration_required" if settings.llm_required else "mock_fallback"
    elif registry._primary and not provider_health.get(registry._primary, True):
        llm_status = "degraded"
    else:
        llm_status = "ready"

    overall = "ok" if db_ok else "degraded"
    return {
        "status": overall,
        "version": "0.1.0",
        "database": "connected" if db_ok else "unreachable",
        "llm_providers": registry.available_providers,
        "llm_primary": registry._primary,
        "llm_required": settings.llm_required,
        "llm_available": bool(registry.available_providers),
        "llm_status": llm_status,
        "llm_provider_health": provider_health,
        "deployment_mode": settings.deployment_mode,
        "code_sandbox_backend": settings.code_sandbox_backend,
        "code_sandbox_runtime": settings.code_sandbox_runtime,
        "code_sandbox_runtime_available": container_runtime_available(),
    }
