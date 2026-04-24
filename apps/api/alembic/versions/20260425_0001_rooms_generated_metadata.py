"""path_rooms generation metadata columns (Phase 16b T1)

Revision ID: 20260425_0001
Revises: 20260424_0002
Create Date: 2026-04-25

Phase 16b room-generation pipeline needs four new metadata fields on
``path_rooms`` so the same table can carry both hand-seeded rooms and
LLM-generated rooms (Variant 1 — one-table-for-all-room-concepts, per
Юрій 2026-04-24). Keeping a single table avoids a parallel ``rooms``
model with its own FKs, relationships, and UI join logic.

Columns added (all nullable except ``room_type``):

* ``generated_at``     — ``DateTime(timezone=True)``, when the LLM run
  finished. ``NULL`` for hand-seeded rooms.
* ``generator_model``  — ``String(100)`` e.g. ``"llama-3.3-70b-versatile"``.
  ``NULL`` for hand-seeded rooms.
* ``generation_seed``  — ``String(128)`` sha256 hex of the canonical
  prompt inputs. Used for idempotence (same hash → same ``room_id``).
  64 chars of sha256 hex + headroom.
* ``room_type``        — ``String(20)`` NOT NULL, ``server_default
  'standard'``. Existing rows backfill to ``'standard'`` automatically;
  generated rooms write ``'generated'``. Using a string (not enum) lets
  future room types ship without another migration.

Idempotent on SQLite via ``op.batch_alter_table`` + inspector column
skip, mirroring the ``20260424_0001_reingest_fk_ondelete`` pattern.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260425_0001"
down_revision: str = "20260424_0002"
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
        if "generated_at" not in existing_columns:
            batch.add_column(
                sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "generator_model" not in existing_columns:
            batch.add_column(
                sa.Column("generator_model", sa.String(length=100), nullable=True)
            )
        if "generation_seed" not in existing_columns:
            batch.add_column(
                sa.Column("generation_seed", sa.String(length=128), nullable=True)
            )
        if "room_type" not in existing_columns:
            batch.add_column(
                sa.Column(
                    "room_type",
                    sa.String(length=20),
                    nullable=False,
                    server_default="standard",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "path_rooms" not in tables:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("path_rooms")}
    with op.batch_alter_table("path_rooms") as batch:
        if "room_type" in existing_columns:
            batch.drop_column("room_type")
        if "generation_seed" in existing_columns:
            batch.drop_column("generation_seed")
        if "generator_model" in existing_columns:
            batch.drop_column("generator_model")
        if "generated_at" in existing_columns:
            batch.drop_column("generated_at")
