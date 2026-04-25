"""user_badges table — Phase 16c Bundle C (Badge backend, Subagent A).

Revision ID: 20260425_0005
Revises: 20260425_0004
Create Date: 2026-04-25

Adds ``user_badges`` — append-only ledger of one-time badge unlocks.
Each row marks "user U unlocked badge K at moment T". The single
``UniqueConstraint(user_id, badge_key)`` is the durable
once-per-(user, badge) guard called for in Bundle C spec D.1: a second
"award" call against an already-unlocked badge must be a no-op rather
than a duplicate row.

Idempotent — re-running ``upgrade`` is a no-op when the table already
exists. Mirrors the style of ``20260425_0004_xp_events.py``.

Schema highlights
-----------------
* ``UniqueConstraint(user_id, badge_key)`` — one-time unlock per spec
  D.1. Insert collisions surface as ``IntegrityError`` which the
  service swallows and treats as "already unlocked" (idempotent
  award).
* Hot index ``(user_id)`` — the ``GET /api/gamification/badges``
  endpoint queries every row for one user; an index on the FK column
  keeps that read O(badges-unlocked).
* ``metadata_json`` is nullable — most awards have no extra context;
  the column is there so future predicates (e.g. "first-card with
  difficulty layer 3") can carry the trigger snapshot without a
  schema change.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260425_0005"
down_revision: str = "20260425_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_badges" not in tables:
        op.create_table(
            "user_badges",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("badge_key", sa.String(length=64), nullable=False),
            sa.Column(
                "unlocked_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_user_badges"),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_user_badges_user_id",
            ),
            sa.UniqueConstraint(
                "user_id",
                "badge_key",
                name="uq_user_badges_user_badge",
            ),
        )

    # Inspect again — table may have been just created above.
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user_badges")}

    if "ix_user_badges_user_id" not in existing_indexes:
        op.create_index(
            "ix_user_badges_user_id",
            "user_badges",
            ["user_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "user_badges" not in tables:
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user_badges")}
    if "ix_user_badges_user_id" in existing_indexes:
        op.drop_index("ix_user_badges_user_id", table_name="user_badges")

    op.drop_table("user_badges")
