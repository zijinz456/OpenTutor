"""Add runtime fields for agent task durability and approval modeling.

Revision ID: 20260304_0014
Revises: 20260304_0013
Create Date: 2026-03-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260304_0014"
down_revision = "20260304_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "agent_tasks" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("agent_tasks")}

    if "task_kind" not in columns:
        op.add_column("agent_tasks", sa.Column("task_kind", sa.String(length=30), nullable=False, server_default="read_only"))
    if "risk_level" not in columns:
        op.add_column("agent_tasks", sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="low"))
    if "approval_status" not in columns:
        op.add_column("agent_tasks", sa.Column("approval_status", sa.String(length=20), nullable=False, server_default="not_required"))
    if "checkpoint_json" not in columns:
        op.add_column("agent_tasks", sa.Column("checkpoint_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "step_results_json" not in columns:
        op.add_column("agent_tasks", sa.Column("step_results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    if "provenance_json" not in columns:
        op.add_column("agent_tasks", sa.Column("provenance_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.execute("UPDATE agent_tasks SET status = 'pending_approval' WHERE status = 'awaiting_approval'")
    op.execute("UPDATE agent_tasks SET status = 'queued' WHERE status = 'retrying'")
    op.execute("UPDATE agent_tasks SET task_kind = 'external_side_effect' WHERE task_type = 'code_execution'")
    op.execute("UPDATE agent_tasks SET risk_level = 'medium' WHERE requires_approval = true")
    op.execute(
        """
        UPDATE agent_tasks
        SET risk_level = 'high'
        WHERE task_type IN ('code_execution', 'semester_init')
        """
    )
    op.execute(
        """
        UPDATE agent_tasks
        SET approval_status = CASE
          WHEN requires_approval = false THEN 'not_required'
          WHEN status = 'pending_approval' THEN 'pending'
          WHEN status = 'rejected' THEN 'rejected'
          WHEN approved_at IS NOT NULL THEN 'approved'
          ELSE 'pending'
        END
        """
    )
    op.execute(
        """
        UPDATE agent_tasks
        SET provenance_json = metadata_json->'provenance'
        WHERE provenance_json IS NULL
          AND metadata_json IS NOT NULL
          AND jsonb_typeof(metadata_json->'provenance') = 'object'
        """
    )
    op.execute(
        """
        UPDATE agent_tasks
        SET step_results_json = result_json->'steps'
        WHERE step_results_json IS NULL
          AND result_json IS NOT NULL
          AND jsonb_typeof(result_json->'steps') = 'array'
        """
    )

    op.alter_column("agent_tasks", "task_kind", server_default=None)
    op.alter_column("agent_tasks", "risk_level", server_default=None)
    op.alter_column("agent_tasks", "approval_status", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "agent_tasks" not in tables:
        return

    columns = {col["name"] for col in inspector.get_columns("agent_tasks")}
    if "provenance_json" in columns:
        op.drop_column("agent_tasks", "provenance_json")
    if "step_results_json" in columns:
        op.drop_column("agent_tasks", "step_results_json")
    if "checkpoint_json" in columns:
        op.drop_column("agent_tasks", "checkpoint_json")
    if "approval_status" in columns:
        op.drop_column("agent_tasks", "approval_status")
    if "risk_level" in columns:
        op.drop_column("agent_tasks", "risk_level")
    if "task_kind" in columns:
        op.drop_column("agent_tasks", "task_kind")
