"""Add ingestion progress and embedding tracking fields.

Revision ID: 20260304_0013
Revises: 20260303_0012
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa


revision = "20260304_0013"
down_revision = "20260303_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "ingestion_jobs" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("ingestion_jobs")}

    if "progress_percent" not in columns:
        op.add_column("ingestion_jobs", sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"))
    if "phase_label" not in columns:
        op.add_column("ingestion_jobs", sa.Column("phase_label", sa.String(length=100), nullable=True))
    if "embedding_status" not in columns:
        op.add_column("ingestion_jobs", sa.Column("embedding_status", sa.String(length=20), nullable=False, server_default="pending"))
    if "nodes_created" not in columns:
        op.add_column("ingestion_jobs", sa.Column("nodes_created", sa.Integer(), nullable=False, server_default="0"))

    op.execute("UPDATE ingestion_jobs SET progress_percent = 100 WHERE status = 'completed'")
    op.execute("UPDATE ingestion_jobs SET embedding_status = 'completed' WHERE status = 'completed'")
    op.execute("UPDATE ingestion_jobs SET progress_percent = 90 WHERE status = 'embedding'")
    op.execute("UPDATE ingestion_jobs SET embedding_status = 'running' WHERE status = 'embedding'")
    op.execute("UPDATE ingestion_jobs SET embedding_status = 'failed' WHERE status = 'failed'")
    op.execute(
        """
        UPDATE ingestion_jobs
        SET nodes_created = COALESCE(
          (dispatched_to->>'content_tree')::int,
          (dispatched_to->>'assignments')::int,
          0
        )
        """
    )

    op.alter_column("ingestion_jobs", "progress_percent", server_default=None)
    op.alter_column("ingestion_jobs", "embedding_status", server_default=None)
    op.alter_column("ingestion_jobs", "nodes_created", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "ingestion_jobs" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("ingestion_jobs")}
    if "nodes_created" in columns:
        op.drop_column("ingestion_jobs", "nodes_created")
    if "embedding_status" in columns:
        op.drop_column("ingestion_jobs", "embedding_status")
    if "phase_label" in columns:
        op.drop_column("ingestion_jobs", "phase_label")
    if "progress_percent" in columns:
        op.drop_column("ingestion_jobs", "progress_percent")
