"""path_rooms mission metadata columns

Revision ID: 20260424_0002
Revises: 20260424_0001
Create Date: 2026-04-24

Slice 0 foundation needs four nullable metadata fields on ``path_rooms``:

* ``outcome``      — one-line practical outcome
* ``difficulty``   — 1..5 mission difficulty
* ``eta_minutes``  — estimated time in minutes
* ``module_label`` — optional grouping label

The migration backfills existing rows with the MVL defaults from ТЗ so a
pre-seeded local DB is immediately usable even before the seed script is
re-run.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260424_0002"
down_revision: str = "20260424_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_DEFAULTS = {
    "outcome": "Complete this mission",
    "difficulty": 2,
    "eta_minutes": 15,
    "module_label": "",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "path_rooms" not in tables:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("path_rooms")}
    with op.batch_alter_table("path_rooms") as batch:
        if "outcome" not in existing_columns:
            batch.add_column(sa.Column("outcome", sa.Text(), nullable=True))
        if "difficulty" not in existing_columns:
            batch.add_column(sa.Column("difficulty", sa.SmallInteger(), nullable=True))
        if "eta_minutes" not in existing_columns:
            batch.add_column(sa.Column("eta_minutes", sa.SmallInteger(), nullable=True))
        if "module_label" not in existing_columns:
            batch.add_column(
                sa.Column("module_label", sa.String(length=80), nullable=True)
            )

    op.execute(
        sa.text(
            """
            UPDATE path_rooms
            SET
              outcome = COALESCE(outcome, :outcome),
              difficulty = COALESCE(difficulty, :difficulty),
              eta_minutes = COALESCE(eta_minutes, :eta_minutes),
              module_label = COALESCE(module_label, :module_label)
            WHERE
              outcome IS NULL
              OR difficulty IS NULL
              OR eta_minutes IS NULL
              OR module_label IS NULL
            """
        ).bindparams(**_DEFAULTS)
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "path_rooms" not in tables:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("path_rooms")}
    with op.batch_alter_table("path_rooms") as batch:
        if "module_label" in existing_columns:
            batch.drop_column("module_label")
        if "eta_minutes" in existing_columns:
            batch.drop_column("eta_minutes")
        if "difficulty" in existing_columns:
            batch.drop_column("difficulty")
        if "outcome" in existing_columns:
            batch.drop_column("outcome")
