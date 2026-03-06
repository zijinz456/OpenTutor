"""Health-check service helpers."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from config import settings
import database as database_module
from services.agent.container_sandbox import container_runtime_available
from services.llm.readiness import get_llm_runtime_status
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


def _database_backend() -> str:
    try:
        return database_module.engine.url.get_backend_name()
    except Exception:
        return "sqlite" if database_module.is_sqlite() else "unknown"


def _local_beta_readiness(
    *,
    db_ok: bool,
    migration_state: MigrationState,
    llm_status: str,
    sandbox_available: bool,
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []

    if not db_ok:
        blockers.append("database_unreachable")
    elif not migration_state.schema_ready:
        blockers.append("schema_not_ready")

    if llm_status in {"mock_fallback", "configuration_required"}:
        blockers.append("llm_not_ready")
    elif llm_status == "degraded":
        blockers.append("llm_unhealthy")

    if not sandbox_available:
        warnings.append("sandbox_runtime_unavailable")

    return blockers, warnings


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

    llm_runtime = await get_llm_runtime_status()
    provider_health = llm_runtime["provider_health"]
    probe_details = llm_runtime["provider_details"]
    llm_status = llm_runtime["status"]
    database_backend = _database_backend()
    sandbox_available = container_runtime_available()
    local_beta_blockers, local_beta_warnings = _local_beta_readiness(
        db_ok=db_ok,
        migration_state=migration_state,
        llm_status=llm_status,
        sandbox_available=sandbox_available,
    )

    overall = "ok" if db_ok and migration_state.schema_ready else "degraded"
    return {
        "status": overall,
        "version": "0.1.0",
        "database_backend": database_backend,
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
        "llm_providers": llm_runtime["available_providers"],
        "llm_primary": llm_runtime["primary_name"],
        "llm_required": settings.llm_required,
        "llm_available": bool(llm_runtime["available_providers"]),
        "llm_status": llm_status,
        "llm_provider_health": provider_health,
        "llm_provider_details": probe_details,
        "deployment_mode": settings.deployment_mode,
        "auth_enabled": settings.auth_enabled,
        "code_sandbox_backend": settings.code_sandbox_backend,
        "code_sandbox_runtime": settings.code_sandbox_runtime,
        "code_sandbox_runtime_available": sandbox_available,
        "local_beta_ready": not local_beta_blockers,
        "local_beta_blockers": local_beta_blockers,
        "local_beta_warnings": local_beta_warnings,
    }
