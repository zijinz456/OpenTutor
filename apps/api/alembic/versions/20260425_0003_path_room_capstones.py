"""path_rooms capstone problem ids column

Revision ID: 20260425_0003
Revises: 20260425_0002
Create Date: 2026-04-25

Slice 2 needs a durable place to store the 3 hardest task ids per room
so later capstone gating can read them without recomputing the ranking
at request time. The column is nullable JSON for SQLite/Postgres parity.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260425_0003"
down_revision: str = "20260425_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "path_rooms" not in tables:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("path_rooms")}
    with op.batch_alter_table("path_rooms") as batch:
        if "capstone_problem_ids" not in existing_columns:
            batch.add_column(
                sa.Column("capstone_problem_ids", sa.JSON(), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "path_rooms" not in tables:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("path_rooms")}
    with op.batch_alter_table("path_rooms") as batch:
        if "capstone_problem_ids" in existing_columns:
            batch.drop_column("capstone_problem_ids")
