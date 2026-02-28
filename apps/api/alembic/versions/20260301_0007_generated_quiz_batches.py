"""Add batch/version fields for generated practice sets.

Revision ID: 20260301_0007
Revises: 20260301_0006
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20260301_0007"
down_revision = "20260301_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "practice_problems" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("practice_problems")}
    if "source_batch_id" not in columns:
        op.add_column("practice_problems", sa.Column("source_batch_id", UUID(as_uuid=True), nullable=True))
    if "source_version" not in columns:
        op.add_column(
            "practice_problems",
            sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        )
    if "is_archived" not in columns:
        op.add_column(
            "practice_problems",
            sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "practice_problems" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("practice_problems")}
    if "is_archived" in columns:
        op.drop_column("practice_problems", "is_archived")
    if "source_version" in columns:
        op.drop_column("practice_problems", "source_version")
    if "source_batch_id" in columns:
        op.drop_column("practice_problems", "source_batch_id")
