"""OpenTutor API — FastAPI entry point."""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from database import engine, Base
from routers import auth, upload, chat, courses, preferences, quiz, notes, workflows, progress, flashcards, canvas, notifications, scrape, scenes, wrong_answers

logger = logging.getLogger(__name__)


async def _maybe_create_tables() -> None:
    if not settings.app_auto_create_tables:
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Auto-created database tables on startup")


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

    await _maybe_create_tables()
    await _maybe_seed_system_data()
    await _maybe_connect_mcp_servers()
    _maybe_start_scheduler()
    yield
    _maybe_stop_scheduler()           # Stop scheduling new tasks first
    await wait_for_background_tasks() # Then wait for in-flight tasks
    await _maybe_disconnect_mcp_servers()
    await engine.dispose()


app = FastAPI(
    title="OpenTutor API",
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


@app.get("/api/health")
async def health():
    from services.llm.router import get_registry
    registry = get_registry()
    return {
        "status": "ok",
        "version": "0.1.0",
        "llm_providers": registry.available_providers,
        "llm_primary": registry._primary,
    }
