"""Tool call lifecycle events table.

Revision ID: 0018_tool_call_events
Revises: 20260306_0017
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "0018_tool_call_events"
down_revision = "20260306_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("tool_call_events"):
        return

    op.create_table(
        "tool_call_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("agent_name", sa.String(64), nullable=False),
        sa.Column("tool_name", sa.String(128), nullable=False),
        sa.Column("input_json", JSONB, nullable=True),
        sa.Column("output_text", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Float, nullable=True),
        sa.Column("iteration", sa.Integer, nullable=False, server_default="0"),
        sa.Column("metadata_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tool_call_user_created", "tool_call_events", ["user_id", "created_at"])
    op.create_index("ix_tool_call_tool_name", "tool_call_events", ["tool_name"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("tool_call_events"):
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes("tool_call_events")}
    if "ix_tool_call_tool_name" in existing_indexes:
        op.drop_index("ix_tool_call_tool_name")
    if "ix_tool_call_user_created" in existing_indexes:
        op.drop_index("ix_tool_call_user_created")
    op.drop_table("tool_call_events")
