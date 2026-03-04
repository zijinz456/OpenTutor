"""Health-check service helpers."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from config import settings
import database as database_module
from services.agent.container_sandbox import container_runtime_available
from services.llm.router import get_registry
from services.migrations import MigrationState, inspect_database_migrations

logger = logging.getLogger(__name__)


def _default_migration_state() -> MigrationState:
    return MigrationState(
        migration_status="unknown",
        schema_ready=False,
        migration_required=True,
        alembic_version_present=False,
        current_revisions=[],
        expected_revisions=[],
    )


async def get_health_status() -> dict[str, Any]:
    db_ok = False
    migration_state = _default_migration_state()
    try:
        async with database_module.async_session() as db:
            await db.execute(text("SELECT 1"))
            conn = await db.connection()
            migration_state = await conn.run_sync(inspect_database_migrations)
        db_ok = True
    except Exception:
        logger.warning("Health check: database unreachable")

    registry = get_registry()

    # Use cached probe results from background monitor (OpenClaw pattern).
    # Falls back to a blocking ping_all() if monitor hasn't run yet.
    probe_details = registry.provider_health_cached
    if probe_details:
        provider_health = {name: d["healthy"] for name, d in probe_details.items()}
    else:
        provider_health = await registry.ping_all()
        probe_details = {
            name: {"healthy": h, "status": "ok" if h else "unhealthy", "error": None}
            for name, h in provider_health.items()
        }

    if not registry.available_providers:
        llm_status = "configuration_required" if settings.llm_required else "mock_fallback"
    elif registry.primary_name == "mock":
        llm_status = "mock_fallback"
    elif registry.primary_name and not provider_health.get(registry.primary_name, True):
        llm_status = "degraded"
    else:
        llm_status = "ready"

    overall = "ok" if db_ok and migration_state.schema_ready else "degraded"
    return {
        "status": overall,
        "version": "0.1.0",
        "database": "connected" if db_ok else "unreachable",
        "schema": (
            "ready"
            if migration_state.schema_ready
            else ("missing" if migration_state.migration_status == "schema_missing" else migration_state.migration_status)
            if db_ok
            else "unknown"
        ),
        "migration_required": bool(db_ok and migration_state.migration_required),
        "migration_status": migration_state.migration_status if db_ok else "unknown",
        "alembic_version_present": migration_state.alembic_version_present if db_ok else False,
        "migration_current_revisions": migration_state.current_revisions if db_ok else [],
        "migration_expected_revisions": migration_state.expected_revisions if db_ok else [],
        "llm_providers": registry.available_providers,
        "llm_primary": registry.primary_name,
        "llm_required": settings.llm_required,
        "llm_available": bool(registry.available_providers),
        "llm_status": llm_status,
        "llm_provider_health": provider_health,
        "llm_provider_details": probe_details,
        "deployment_mode": settings.deployment_mode,
        "auth_enabled": settings.auth_enabled,
        "code_sandbox_backend": settings.code_sandbox_backend,
        "code_sandbox_runtime": settings.code_sandbox_runtime,
        "code_sandbox_runtime_available": container_runtime_available(),
    }
