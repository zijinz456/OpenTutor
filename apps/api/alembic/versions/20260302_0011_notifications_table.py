"""Add notifications table for persistent push notifications.

Revision ID: 20260302_0011
Revises: 20260302_0010
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260302_0011"
down_revision = "20260302_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "notifications" not in tables:
        op.create_table(
            "notifications",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("category", sa.String(50), nullable=False),
            sa.Column("read", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_notification_user_read_created", "notifications", ["user_id", "read", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "notifications" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("notifications")}
        if "ix_notification_user_read_created" in indexes:
            op.drop_index("ix_notification_user_read_created", table_name="notifications")
        op.drop_table("notifications")
