"""Application startup and shutdown hooks."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

import httpx
from sqlalchemy import text

from config import settings
import database as database_module
from database import Base, engine
from services.migrations import bootstrap_alembic_version_table

logger = logging.getLogger(__name__)


async def _maybe_create_tables() -> None:
    if not settings.app_auto_create_tables:
        return

    async with engine.begin() as conn:
        if not database_module.is_sqlite():
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Ensured database tables exist via Base.metadata.create_all()")


async def _maybe_bootstrap_migration_tracking() -> None:
    if not settings.app_auto_create_tables or database_module.is_sqlite():
        return

    async with engine.begin() as conn:
        stamped_heads = await conn.run_sync(bootstrap_alembic_version_table)

    if stamped_heads:
        logger.info(
            "Stamped alembic_version after local schema bootstrap (%s)",
            ", ".join(stamped_heads),
        )


async def _maybe_seed_system_data() -> None:
    if not settings.app_auto_seed_system:
        return

    from database import async_session
    from services.templates.system import seed_builtin_templates
    from services.templates.demo_course import seed_demo_course

    async with async_session() as db:
        await seed_builtin_templates(db)
        created = await seed_demo_course(db)
        await db.commit()
    logger.info("Seeded built-in templates")
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
    if not settings.mcp_enabled:
        logger.info("MCP tool loading disabled by configuration")
        return

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
    if not settings.mcp_enabled:
        return

    try:
        from services.agent.tools.mcp_client import shutdown_mcp_providers

        await shutdown_mcp_providers()
    except Exception as exc:
        logger.debug("MCP disconnect: %s", exc)


async def _detect_local_llm() -> None:
    """Detect local LLM providers (Ollama, LM Studio) on startup.

    If a provider is found and no explicit LLM is configured,
    auto-configure it so the user doesn't need to edit .env.
    Inspired by OpenClaw's auto-detection and AnythingLLM's provider discovery.
    """
    import asyncio

    detected: list[dict] = []

    async def _probe_ollama() -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{settings.ollama_base_url}/api/tags")
                if resp.status_code == 200:
                    models = resp.json().get("models", [])
                    return {"provider": "ollama", "url": settings.ollama_base_url, "models": [m.get("name", "?") for m in models]}
        except Exception:
            pass
        return None

    async def _probe_lmstudio() -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{settings.lmstudio_base_url}/models")
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m["id"] for m in data.get("data", [])]
                    return {"provider": "lmstudio", "url": settings.lmstudio_base_url, "models": models}
        except Exception:
            pass
        return None

    results = await asyncio.gather(_probe_ollama(), _probe_lmstudio(), return_exceptions=True)
    for r in results:
        if isinstance(r, dict) and r is not None:
            detected.append(r)

    if not detected:
        if settings.llm_provider.lower() in ("ollama", "lmstudio"):
            logger.warning(
                "No local LLM detected. Install Ollama (https://ollama.com) "
                "or set LLM_PROVIDER / API keys for a cloud provider."
            )
        return

    for p in detected:
        model_count = len(p["models"])
        names = ", ".join(p["models"][:5])
        if model_count > 0:
            logger.info(
                "%s detected at %s with %d model(s): %s",
                p["provider"].upper(), p["url"], model_count, names,
            )
        else:
            logger.warning(
                "%s is running at %s but has no models loaded.",
                p["provider"].upper(), p["url"],
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
    if not settings.plugin_system_enabled:
        logger.info("Plugin system disabled by configuration")
        return

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
    if not settings.plugin_system_enabled:
        return

    try:
        from services.plugin.manager import get_plugin_manager

        pm = get_plugin_manager()
        await pm.shutdown()
    except Exception as exc:
        logger.debug("Plugin system shutdown: %s", exc)


async def run_startup_hooks() -> None:
    await _maybe_create_tables()
    await _maybe_bootstrap_migration_tracking()
    await _maybe_seed_system_data()
    await _detect_local_llm()
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
