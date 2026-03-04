"""Application startup and shutdown hooks."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx

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
    from services.templates.demo_course import seed_demo_course

    async with async_session() as db:
        await seed_builtin_templates(db)
        await seed_preset_scenes(db)
        created = await seed_demo_course(db)
        await db.commit()
    logger.info("Seeded built-in templates and preset scenes")
    if created:
        logger.info("Created demo course for first-time experience")


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


async def _detect_ollama() -> None:
    """Detect local Ollama on startup and log helpful guidance."""
    if settings.llm_provider.lower() != "ollama":
        return
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if models:
                    names = [m.get("name", "?") for m in models[:5]]
                    logger.info(
                        "Ollama detected with %d model(s): %s",
                        len(models), ", ".join(names),
                    )
                else:
                    logger.warning(
                        "Ollama is running but has no models. "
                        "Pull one with:  ollama pull llama3.2:3b"
                    )
            else:
                logger.warning("Ollama responded with status %d", resp.status_code)
    except Exception:
        logger.warning(
            "Ollama not detected at %s. "
            "Install from https://ollama.com or set LLM_PROVIDER / API keys "
            "for a cloud provider.",
            settings.ollama_base_url,
        )


def _start_health_monitor() -> None:
    """Start background LLM health probe loop (OpenClaw pattern)."""
    from services.llm.router import get_registry

    registry = get_registry()
    registry.start_health_monitor(interval=30.0)


async def _stop_health_monitor() -> None:
    from services.llm.router import get_registry

    registry = get_registry()
    await registry.stop_health_monitor()


async def _maybe_setup_checkpointer() -> None:
    """Initialise LangGraph checkpoint persistence (PostgreSQL-backed).

    After setup, invalidates cached graph singletons so they re-compile
    with the now-available checkpointer.
    """
    try:
        from services.workflow.checkpoint import setup_checkpointer
        await setup_checkpointer()
        # Invalidate any graphs that were compiled before the checkpointer was ready
        from services.workflow.graph import invalidate_graph_singletons
        invalidate_graph_singletons()
    except Exception as exc:
        logger.warning("Checkpoint setup failed (workflows will run without persistence): %s", exc)


async def _maybe_teardown_checkpointer() -> None:
    try:
        from services.workflow.checkpoint import teardown_checkpointer
        await teardown_checkpointer()
    except Exception:
        pass


async def _start_plugin_system() -> None:
    """Initialize pluggy-based plugin system and call startup hooks."""
    try:
        from services.plugin.manager import get_plugin_manager

        pm = get_plugin_manager()
        pm.load_all()
        await pm.startup()
        logger.info(
            "Plugin system started (%d plugin(s): %s)",
            len(pm.manifests),
            ", ".join(pm.manifests.keys()) or "none",
        )
    except Exception as exc:
        logger.warning("Plugin system startup failed (graceful degradation): %s", exc)


async def _stop_plugin_system() -> None:
    try:
        from services.plugin.manager import get_plugin_manager

        pm = get_plugin_manager()
        await pm.shutdown()
    except Exception as exc:
        logger.debug("Plugin system shutdown: %s", exc)


async def run_startup_hooks() -> None:
    await _maybe_create_tables()
    await _maybe_seed_system_data()
    await _detect_ollama()
    await _maybe_setup_checkpointer()
    await _maybe_connect_mcp_servers()
    await _start_plugin_system()
    _maybe_start_scheduler()
    _maybe_start_activity_engine()
    _start_health_monitor()


async def run_shutdown_hooks() -> None:
    from services.agent.orchestrator import wait_for_background_tasks

    await _stop_health_monitor()
    await _maybe_stop_activity_engine()
    _maybe_stop_scheduler()
    await wait_for_background_tasks()
    await _stop_plugin_system()
    await _maybe_disconnect_mcp_servers()
    await _maybe_teardown_checkpointer()
    await engine.dispose()


@asynccontextmanager
async def lifespan(_: object):
    os.makedirs(settings.upload_dir, exist_ok=True)
    await run_startup_hooks()
    yield
    await run_shutdown_hooks()
