"""Add agent tasks and chat metadata.

Revision ID: 20260302_0009
Revises: 20260301_0008
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260302_0009"
down_revision = "20260301_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())

    if "chat_message_logs" in tables:
        columns = {col["name"] for col in inspector.get_columns("chat_message_logs")}
        if "metadata_json" not in columns:
            op.add_column("chat_message_logs", sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    if "agent_tasks" not in tables:
        op.create_table(
            "agent_tasks",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("task_type", sa.String(length=50), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=30), nullable=False),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_agent_task_user_course_created",
            "agent_tasks",
            ["user_id", "course_id", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_agent_task_user_status_created",
            "agent_tasks",
            ["user_id", "status", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if "agent_tasks" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("agent_tasks")}
        if "ix_agent_task_user_course_created" in indexes:
            op.drop_index("ix_agent_task_user_course_created", table_name="agent_tasks")
        if "ix_agent_task_user_status_created" in indexes:
            op.drop_index("ix_agent_task_user_status_created", table_name="agent_tasks")
        op.drop_table("agent_tasks")

    if "chat_message_logs" in tables:
        columns = {col["name"] for col in inspector.get_columns("chat_message_logs")}
        if "metadata_json" in columns:
            op.drop_column("chat_message_logs", "metadata_json")
