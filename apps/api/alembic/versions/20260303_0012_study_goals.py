"""Add study goals table and optional goal linkage on agent tasks.

Revision ID: 20260303_0012
Revises: 20260303_0010
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260303_0012"
down_revision = "20260303_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())

    if "study_goals" not in tables:
        op.create_table(
            "study_goals",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("objective", sa.Text(), nullable=False),
            sa.Column("success_metric", sa.String(length=200), nullable=True),
            sa.Column("current_milestone", sa.String(length=200), nullable=True),
            sa.Column("next_action", sa.String(length=200), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("confidence", sa.String(length=20), nullable=True),
            sa.Column("target_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_study_goal_user_course_status_created",
            "study_goals",
            ["user_id", "course_id", "status", "created_at"],
            unique=False,
        )
        op.create_index(
            "ix_study_goal_user_status_target",
            "study_goals",
            ["user_id", "status", "target_date"],
            unique=False,
        )

    if "agent_tasks" in tables:
        columns = {col["name"] for col in inspector.get_columns("agent_tasks")}
        if "goal_id" not in columns:
            op.add_column("agent_tasks", sa.Column("goal_id", postgresql.UUID(as_uuid=True), nullable=True))
            op.create_foreign_key(
                "fk_agent_tasks_goal_id_study_goals",
                "agent_tasks",
                "study_goals",
                ["goal_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "agent_tasks" in tables:
        columns = {col["name"] for col in inspector.get_columns("agent_tasks")}
        foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("agent_tasks") if fk.get("name")}
        if "fk_agent_tasks_goal_id_study_goals" in foreign_keys:
            op.drop_constraint("fk_agent_tasks_goal_id_study_goals", "agent_tasks", type_="foreignkey")
        if "goal_id" in columns:
            op.drop_column("agent_tasks", "goal_id")

    if "study_goals" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("study_goals")}
        if "ix_study_goal_user_status_target" in indexes:
            op.drop_index("ix_study_goal_user_status_target", table_name="study_goals")
        if "ix_study_goal_user_course_status_created" in indexes:
            op.drop_index("ix_study_goal_user_course_status_created", table_name="study_goals")
        op.drop_table("study_goals")
