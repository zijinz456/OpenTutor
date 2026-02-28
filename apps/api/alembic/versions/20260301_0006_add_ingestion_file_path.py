"""Add ingestion_jobs.file_path for persisted uploads.

Revision ID: 20260301_0006
Revises: 20260301_0005
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260301_0006"
down_revision = "20260301_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ingestion_jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("ingestion_jobs")}
    if "file_path" not in columns:
        op.add_column(
            "ingestion_jobs",
            sa.Column("file_path", sa.String(length=1000), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "ingestion_jobs" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("ingestion_jobs")}
    if "file_path" in columns:
        op.drop_column("ingestion_jobs", "file_path")
