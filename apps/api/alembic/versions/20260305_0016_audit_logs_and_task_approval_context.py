"""add audit logs and task approval descriptors

Revision ID: 20260305_0016_audit
Revises: 20260305_0016_merge
Create Date: 2026-03-05 10:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260305_0016_audit"
down_revision = "20260305_0016_merge"
branch_labels = None
depends_on = None


def _table_columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    task_columns = _table_columns("agent_tasks")
    if "approval_reason" not in task_columns:
        op.add_column("agent_tasks", sa.Column("approval_reason", sa.Text(), nullable=True))
    if "approval_action" not in task_columns:
        op.add_column("agent_tasks", sa.Column("approval_action", sa.Text(), nullable=True))

    inspector = sa.inspect(op.get_bind())
    if "audit_logs" not in inspector.get_table_names():
        op.create_table(
            "audit_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("tool_name", sa.String(length=80), nullable=True),
            sa.Column("action_kind", sa.String(length=80), nullable=False),
            sa.Column("approval_status", sa.String(length=20), nullable=True),
            sa.Column("outcome", sa.String(length=40), nullable=False),
            sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"])
        op.create_index("ix_audit_logs_task_created", "audit_logs", ["task_id", "created_at"])
        op.create_index("ix_audit_logs_action_created", "audit_logs", ["action_kind", "created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "audit_logs" in inspector.get_table_names():
        op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
        op.drop_index("ix_audit_logs_task_created", table_name="audit_logs")
        op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
        op.drop_table("audit_logs")

    task_columns = _table_columns("agent_tasks")
    if "approval_action" in task_columns:
        op.drop_column("agent_tasks", "approval_action")
    if "approval_reason" in task_columns:
        op.drop_column("agent_tasks", "approval_reason")
