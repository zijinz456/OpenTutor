"""Add action/dedup/priority fields to notifications.

Revision ID: 0020_notification_actions
Revises: 0019_agent_kv
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020_notification_actions"
down_revision = "0019_agent_kv"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "notifications" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("notifications")}

    if "action_url" not in columns:
        op.add_column("notifications", sa.Column("action_url", sa.String(500), nullable=True))
    if "action_label" not in columns:
        op.add_column("notifications", sa.Column("action_label", sa.String(100), nullable=True))
    if "metadata_json" not in columns:
        op.add_column("notifications", sa.Column("metadata_json", postgresql.JSONB(), nullable=True))
    if "batch_key" not in columns:
        op.add_column("notifications", sa.Column("batch_key", sa.String(100), nullable=True))
    if "dedup_key" not in columns:
        op.add_column("notifications", sa.Column("dedup_key", sa.String(200), nullable=True))
    if "priority" not in columns:
        op.add_column("notifications", sa.Column("priority", sa.String(20), server_default="normal", nullable=False))
    if "scheduled_for" not in columns:
        op.add_column("notifications", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    if "sent_via" not in columns:
        op.add_column("notifications", sa.Column("sent_via", postgresql.JSONB(), nullable=True))

    # Partial unique index on dedup_key
    indexes = {idx["name"] for idx in inspector.get_indexes("notifications")}
    if "ix_notification_dedup_key" not in indexes:
        op.create_index(
            "ix_notification_dedup_key",
            "notifications",
            ["dedup_key"],
            unique=True,
            postgresql_where=sa.text("dedup_key IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "notifications" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("notifications")}
    if "ix_notification_dedup_key" in indexes:
        op.drop_index("ix_notification_dedup_key", table_name="notifications")

    columns = {c["name"] for c in inspector.get_columns("notifications")}
    for col in ("sent_via", "scheduled_for", "priority", "dedup_key", "batch_key", "metadata_json", "action_label", "action_url"):
        if col in columns:
            op.drop_column("notifications", col)
