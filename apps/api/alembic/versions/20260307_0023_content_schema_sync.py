"""Backfill missing content/practice columns for PostgreSQL deployments.

Revision ID: 0023_content_schema_sync
Revises: 0022_integration_credentials
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_content_schema_sync"
down_revision = "0022_integration_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "course_content_tree" in tables:
        columns = {col["name"] for col in inspector.get_columns("course_content_tree")}
        if "blocks_json" not in columns:
            op.add_column("course_content_tree", sa.Column("blocks_json", postgresql.JSONB(), nullable=True))

    if "practice_problems" in tables:
        columns = {col["name"] for col in inspector.get_columns("practice_problems")}
        if "source_owner" not in columns:
            op.add_column(
                "practice_problems",
                sa.Column("source_owner", sa.String(length=20), nullable=False, server_default="ai"),
            )
        if "locked" not in columns:
            op.add_column(
                "practice_problems",
                sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "practice_problems" in tables:
        columns = {col["name"] for col in inspector.get_columns("practice_problems")}
        if "locked" in columns:
            op.drop_column("practice_problems", "locked")
        if "source_owner" in columns:
            op.drop_column("practice_problems", "source_owner")

    if "course_content_tree" in tables:
        columns = {col["name"] for col in inspector.get_columns("course_content_tree")}
        if "blocks_json" in columns:
            op.drop_column("course_content_tree", "blocks_json")
