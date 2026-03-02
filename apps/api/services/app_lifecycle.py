"""Application startup and shutdown hooks."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from config import settings
from database import Base, engine

logger = logging.getLogger(__name__)


async def _maybe_create_tables() -> None:
    if not settings.app_auto_create_tables:
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Ensured database tables exist via Base.metadata.create_all()")


async def _maybe_seed_system_data() -> None:
    if not settings.app_auto_seed_system:
        return

    from database import async_session
    from services.scene.seed import seed_preset_scenes
    from services.templates.system import seed_builtin_templates

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
        else:
            logger.info("No MCP tools registered (none configured or all servers unavailable)")
    except Exception as exc:
        logger.warning("MCP subsystem initialization failed (graceful degradation): %s", exc)


async def _maybe_disconnect_mcp_servers() -> None:
    try:
        from services.agent.tools.mcp_client import shutdown_mcp_providers

        await shutdown_mcp_providers()
    except Exception as exc:
        logger.debug("MCP disconnect: %s", exc)


async def run_startup_hooks() -> None:
    await _maybe_create_tables()
    await _maybe_seed_system_data()
    await _maybe_connect_mcp_servers()
    _maybe_start_scheduler()
    _maybe_start_activity_engine()


async def run_shutdown_hooks() -> None:
    from services.agent.orchestrator import wait_for_background_tasks

    await _maybe_stop_activity_engine()
    _maybe_stop_scheduler()
    await wait_for_background_tasks()
    await _maybe_disconnect_mcp_servers()
    await engine.dispose()


@asynccontextmanager
async def lifespan(_: object):
    os.makedirs(settings.upload_dir, exist_ok=True)
    await run_startup_hooks()
    yield
    await run_shutdown_hooks()
