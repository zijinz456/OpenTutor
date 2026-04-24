"""reingest FK hardening: ondelete=SET NULL on course_content_tree references

Revision ID: 20260424_0001
Revises: 20260423_0003
Create Date: 2026-04-24

Day-0 fix for the re-ingest crash: POSTing the same URL to a course that
already ingested it hits ``sqlite3.IntegrityError: FOREIGN KEY constraint
failed`` on ``DELETE FROM course_content_tree`` inside
``services.ingestion.dispatch.dispatch_content``. The Python dedup path in
that function nullifies ``practice_problems.content_node_id`` before the
delete, but (a) the DB-level FK has no ``ondelete`` clause so the schema
does not enforce the invariant if the Python path is ever bypassed, and
(b) the legacy ``knowledge_points`` scene-system table has an unhandled
FK into ``course_content_tree`` on installs where it exists.

This migration brings the DB schema in line with what the dispatch code
already assumes:

* ``practice_problems.content_node_id`` → ``course_content_tree.id``
  gets ``ondelete='SET NULL'``. The empty ``2870051cd576`` migration was
  meant to do this; it never actually altered anything.
* ``knowledge_points.source_content_node_id`` → same. Guarded so installs
  without the scene-system table are a no-op.

Both alterations are idempotent: if the existing FK already carries
``ondelete='SET NULL'`` the change is skipped. Uses
``op.batch_alter_table`` so the rewrite works on SQLite (which needs a
CREATE TABLE…SELECT cycle for FK changes) and Postgres (where the batch
compiles down to plain ALTER TABLE … DROP/ADD CONSTRAINT).
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260424_0001"
down_revision: str = "20260423_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# Tables and their (column, referenced_table.column) that need
# ``ondelete='SET NULL'`` hardening. Ordered to keep downgrade symmetric.
_FK_TARGETS: list[tuple[str, str, str, str]] = [
    # (table, column, ref_table, ref_col)
    ("practice_problems", "content_node_id", "course_content_tree", "id"),
    ("knowledge_points", "source_content_node_id", "course_content_tree", "id"),
]


def _find_fk(
    inspector: sa.engine.reflection.Inspector, table: str, column: str
) -> dict | None:
    """Return the FK dict whose ``constrained_columns`` is exactly ``[column]``.

    Returns ``None`` if no FK on that column exists. Auto-generated FK
    constraint names are common in this schema, so we match by column
    instead of by name.
    """
    for fk in inspector.get_foreign_keys(table):
        if fk.get("constrained_columns") == [column]:
            return fk
    return None


def _rebuild_fk(
    table: str,
    column: str,
    ref_table: str,
    ref_col: str,
    existing_fk: dict,
    new_fk_name: str,
    ondelete: str | None,
) -> None:
    """Drop the existing (possibly anonymous) FK and create a named one.

    Runs inside a single ``batch_alter_table`` context so SQLite rewrites
    the table exactly once. On Postgres this is a metadata operation.
    """
    old_name = existing_fk.get("name")
    with op.batch_alter_table(table) as batch:
        if old_name:
            batch.drop_constraint(old_name, type_="foreignkey")
        # Auto-generated / unnamed FKs: batch_alter_table on SQLite
        # recognises them by columns+ref and will drop on the rewrite.
        # Add the replacement with the same columns.
        batch.create_foreign_key(
            new_fk_name,
            ref_table,
            [column],
            [ref_col],
            ondelete=ondelete,
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, column, ref_table, ref_col in _FK_TARGETS:
        if table not in tables:
            # knowledge_points only exists on installs that ran the
            # v3-scene-system migration (20260228_0003). Skipping is
            # correct — there's no FK to harden.
            continue

        existing_fk = _find_fk(inspector, table, column)
        if existing_fk is None:
            # Column exists but no FK — unusual but not something we
            # should invent here. Skip rather than create unexpected FK.
            continue

        current_ondelete = (existing_fk.get("options") or {}).get("ondelete")
        if (current_ondelete or "").upper() == "SET NULL":
            # Already hardened — idempotent no-op.
            continue

        _rebuild_fk(
            table=table,
            column=column,
            ref_table=ref_table,
            ref_col=ref_col,
            existing_fk=existing_fk,
            new_fk_name=f"fk_{table}_{column}_set_null",
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Reverse: drop named FK and recreate without ondelete.

    Note: SQLite can't introspect the pre-migration constraint name
    (often anonymous), so we recreate without a name either. Callers
    re-running an upgrade will rebuild it.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, column, ref_table, ref_col in _FK_TARGETS:
        if table not in tables:
            continue

        existing_fk = _find_fk(inspector, table, column)
        if existing_fk is None:
            continue

        new_name = f"fk_{table}_{column}_set_null"
        if existing_fk.get("name") != new_name:
            # Not the FK we installed — leave it alone.
            continue

        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(new_name, type_="foreignkey")
            batch.create_foreign_key(
                None,
                ref_table,
                [column],
                [ref_col],
            )
