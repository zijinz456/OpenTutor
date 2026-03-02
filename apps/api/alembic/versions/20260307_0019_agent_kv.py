"""General-purpose agent key-value store.

Revision ID: 0019_agent_kv
Revises: 0018_tool_call_events
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0019_agent_kv"
down_revision = "0018_tool_call_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agent_kv"):
        return

    op.create_table(
        "agent_kv",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=True),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("value_json", postgresql.JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_agent_kv_user_course_ns_key", "agent_kv", ["user_id", "course_id", "namespace", "key"])
    op.create_index("ix_agent_kv_user_ns", "agent_kv", ["user_id", "namespace"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("agent_kv"):
        return

    existing_indexes = {index["name"] for index in inspector.get_indexes("agent_kv")}
    if "ix_agent_kv_user_ns" in existing_indexes:
        op.drop_index("ix_agent_kv_user_ns")
    op.drop_table("agent_kv")
