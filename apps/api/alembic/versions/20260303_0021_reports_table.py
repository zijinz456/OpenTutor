"""Add reports table for persisted daily briefs and weekly reports.

Revision ID: 0021_reports
Revises: 0020_notification_actions
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_reports"
down_revision = "0020_notification_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "reports" in inspector.get_table_names():
        return

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("report_type", sa.String(30), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_user_type_created", "reports", ["user_id", "report_type", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "reports" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("reports")}
    if "ix_report_user_type_created" in indexes:
        op.drop_index("ix_report_user_type_created", table_name="reports")
    op.drop_table("reports")
