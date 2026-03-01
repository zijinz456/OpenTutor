"""Add execution fields for durable agent tasks.

Revision ID: 20260303_0010
Revises: 20260302_0009
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260303_0010"
down_revision = "20260302_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if "agent_tasks" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("agent_tasks")}
    indexes = {idx["name"] for idx in inspector.get_indexes("agent_tasks")}

    if "input_json" not in columns:
        op.add_column("agent_tasks", sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "attempts" not in columns:
        op.add_column("agent_tasks", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    if "max_attempts" not in columns:
        op.add_column("agent_tasks", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"))
    if "requires_approval" not in columns:
        op.add_column("agent_tasks", sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "approved_at" not in columns:
        op.add_column("agent_tasks", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    if "started_at" not in columns:
        op.add_column("agent_tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    if "cancel_requested_at" not in columns:
        op.add_column("agent_tasks", sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))
    if "ix_agent_task_status_approval_created" not in indexes:
        op.create_index(
            "ix_agent_task_status_approval_created",
            "agent_tasks",
            ["status", "requires_approval", "created_at"],
            unique=False,
        )

    op.alter_column("agent_tasks", "attempts", server_default=None)
    op.alter_column("agent_tasks", "max_attempts", server_default=None)
    op.alter_column("agent_tasks", "requires_approval", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if "agent_tasks" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("agent_tasks")}
    indexes = {idx["name"] for idx in inspector.get_indexes("agent_tasks")}

    if "ix_agent_task_status_approval_created" in indexes:
        op.drop_index("ix_agent_task_status_approval_created", table_name="agent_tasks")
    for column in [
        "cancel_requested_at",
        "started_at",
        "approved_at",
        "requires_approval",
        "max_attempts",
        "attempts",
        "input_json",
    ]:
        if column in columns:
            op.drop_column("agent_tasks", column)
