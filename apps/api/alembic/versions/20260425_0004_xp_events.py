"""xp_events table — Phase 16c Story 2 backend foundation

Revision ID: 20260425_0004
Revises: 20260425_0003
Create Date: 2026-04-25

Adds the append-only ``xp_events`` ledger underpinning the gamification
layer (Story 1 #6 — XP total derived, never materialized) and Story 2
(XP award per practice result / room complete).

Idempotent — re-running ``upgrade`` is a no-op when the table already
exists. Mirrors the style of ``20260425_0003_path_room_capstones.py``.

Schema highlights
-----------------
* ``CHECK (amount BETWEEN -5 AND 200)`` — final guard against service
  bugs (Story 2 #2 + #3 cap).
* Hot index ``(user_id, earned_at)`` — dashboard queries the latest N
  events per user.
* Anti-spam unique index ``(user_id, source_id, date(earned_at))`` —
  Story 2 #3: re-answering the same card today awards 0 XP. Functional
  index using ``date(earned_at)`` works on both SQLite (parses
  ``date(...)`` as a SQL function call) and Postgres (``date(... at
  time zone 'UTC')`` would be the production form, but SQLite has no
  ``AT TIME ZONE`` operator — using plain ``date(earned_at)`` is the
  portable choice that still de-dupes per local-day on SQLite, which
  is the local-only posture of the project anyway).
* Partial: ``WHERE source_id IS NOT NULL`` so manual grants without a
  source row don't collide with each other. SQLite supports partial
  indexes natively since 3.8.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260425_0004"
down_revision: str = "20260425_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "xp_events" not in tables:
        op.create_table(
            "xp_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=64), nullable=False),
            sa.Column("source_id", sa.String(length=36), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column(
                "earned_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id", name="pk_xp_events"),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_xp_events_user_id",
            ),
            sa.CheckConstraint(
                "amount BETWEEN -5 AND 200",
                name="ck_xp_events_amount_range",
            ),
        )

    # Inspect again — table may have been just created above.
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("xp_events")}

    if "ix_xp_events_user_id" not in existing_indexes:
        op.create_index(
            "ix_xp_events_user_id",
            "xp_events",
            ["user_id"],
            unique=False,
        )

    if "ix_xp_events_user_earned" not in existing_indexes:
        op.create_index(
            "ix_xp_events_user_earned",
            "xp_events",
            ["user_id", "earned_at"],
            unique=False,
        )

    if "uq_xp_events_user_source_day" not in existing_indexes:
        # Functional partial unique index for anti-spam (Story 2 #3).
        # ``sa.text("date(earned_at)")`` lets the index target the
        # SQL ``date(...)`` extraction; SQLAlchemy emits it verbatim.
        # The partial ``WHERE source_id IS NOT NULL`` keeps manual
        # grants (NULL source_id) out of the dedup bucket.
        op.create_index(
            "uq_xp_events_user_source_day",
            "xp_events",
            ["user_id", "source_id", sa.text("date(earned_at)")],
            unique=True,
            sqlite_where=sa.text("source_id IS NOT NULL"),
            postgresql_where=sa.text("source_id IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "xp_events" not in tables:
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("xp_events")}
    for ix_name in (
        "uq_xp_events_user_source_day",
        "ix_xp_events_user_earned",
        "ix_xp_events_user_id",
    ):
        if ix_name in existing_indexes:
            op.drop_index(ix_name, table_name="xp_events")

    op.drop_table("xp_events")
