"""freeze tokens table

Revision ID: 20260423_0002
Revises: 20260423_0001
Create Date: 2026-04-23

One-table migration for Phase 14 T1 ADHD UX "❄ Freeze". Mirrors the
Phase 5 Interviewer migration (``20260423_0001``) pattern — same
``_uuid_type()`` helper so the DDL compiles on both the Postgres target
and the SQLite CI validation backend.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from models.compat import CompatUUID


revision = "20260423_0002"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None


def _uuid_type():
    """Native UUID on Postgres, ``CompatUUID`` (VARCHAR(36)) on SQLite.

    Mirrors the ORM's cross-dialect type so the migration compiles on both
    the CI SQLite validation backend and the production Postgres target.
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return CompatUUID()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    uuid_t = _uuid_type()

    if "freeze_tokens" not in tables:
        op.create_table(
            "freeze_tokens",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("user_id", uuid_t, nullable=False),
            sa.Column("problem_id", uuid_t, nullable=False),
            sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["problem_id"], ["practice_problems.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "user_id", "problem_id", name="uq_freeze_token_user_problem"
            ),
        )
        op.create_index(
            "ix_freeze_tokens_user_expires",
            "freeze_tokens",
            ["user_id", "expires_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "freeze_tokens" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("freeze_tokens")}
        if "ix_freeze_tokens_user_expires" in indexes:
            op.drop_index("ix_freeze_tokens_user_expires", table_name="freeze_tokens")
        op.drop_table("freeze_tokens")
