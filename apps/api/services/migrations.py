"""Helpers for inspecting Alembic migration state."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
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
    users_table = connection.execute(sa.text("SELECT to_regclass('users')")).scalar()
    version_table = connection.execute(sa.text("SELECT to_regclass('alembic_version')")).scalar()
    table_names = {
        name
        for name, present in (
            ("users", users_table is not None),
            ("alembic_version", version_table is not None),
        )
        if present
    }
    current_heads: tuple[str, ...] = ()

    try:
        if "alembic_version" in table_names:
            context = MigrationContext.configure(connection)
            current_heads = tuple(context.get_current_heads())
        expected_heads = get_expected_migration_heads()
    except Exception:
        return MigrationState(
            migration_status="inspection_error",
            schema_ready=False,
            migration_required=True,
            alembic_version_present="alembic_version" in table_names,
            current_revisions=sorted(set(current_heads)),
            expected_revisions=[],
        )

    return summarize_migration_state(
        table_names=table_names,
        current_heads=current_heads,
        expected_heads=expected_heads,
    )
