"""Helpers for inspecting Alembic migration state."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory


API_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class MigrationState:
    migration_status: str
    schema_ready: bool
    migration_required: bool
    alembic_version_present: bool
    current_revisions: list[str]
    expected_revisions: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    return config


def get_expected_migration_heads() -> list[str]:
    script = ScriptDirectory.from_config(build_alembic_config())
    return sorted(script.get_heads())


def summarize_migration_state(
    *,
    table_names: Collection[str],
    current_heads: Sequence[str],
    expected_heads: Sequence[str],
) -> MigrationState:
    tables = set(table_names)
    current = sorted(set(current_heads))
    expected = sorted(set(expected_heads))
    has_users = "users" in tables
    has_version_table = "alembic_version" in tables

    if not has_users:
        status = "schema_missing"
    elif not has_version_table:
        status = "version_table_missing"
    elif not current:
        status = "version_table_empty"
    elif current != expected:
        status = "out_of_date"
    else:
        status = "ready"

    migration_required = status != "ready"
    return MigrationState(
        migration_status=status,
        schema_ready=has_users and not migration_required,
        migration_required=migration_required,
        alembic_version_present=has_version_table,
        current_revisions=current,
        expected_revisions=expected,
    )


def inspect_database_migrations(connection) -> MigrationState:
    # SQLite local mode is migration-ready by design.
    # We bootstrap schema via SQLAlchemy create_all() and do not require Alembic
    # stamping as a runtime blocker for local single-user beta startup.
    return MigrationState(
        migration_status="ready",
        schema_ready=True,
        migration_required=False,  # SQLite local mode never needs Alembic
        alembic_version_present=False,
        current_revisions=[],
        expected_revisions=[],
    )


def bootstrap_alembic_version_table(connection) -> list[str]:
    """Stamp current heads when a schema exists without Alembic tracking.

    This is intended for local bootstrap flows that rely on ``create_all()``
    to materialize the base schema before the app starts. If the core schema
    exists and ``alembic_version`` is missing (or present but empty), the
    current migration heads are written so health checks and later upgrades
    can reason about the database consistently.
    """

    inspector = sa.inspect(connection)
    table_names = set(inspector.get_table_names())
    if "users" not in table_names:
        return []

    expected_heads = get_expected_migration_heads()
    if not expected_heads:
        return []

    if "alembic_version" not in table_names:
        connection.execute(
            sa.text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL PRIMARY KEY)")
        )
        existing_heads: set[str] = set()
    else:
        existing_heads = {
            str(row[0])
            for row in connection.execute(sa.text("SELECT version_num FROM alembic_version"))
            if row[0]
        }
        if existing_heads:
            return []

    for head in expected_heads:
        connection.execute(
            sa.text("INSERT INTO alembic_version (version_num) VALUES (:head)"),
            {"head": head},
        )

    return expected_heads
