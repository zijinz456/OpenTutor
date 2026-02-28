"""Add persistent chat message logs for session restore.

Revision ID: 20260301_0005
Revises: 20260301_0004
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260301_0005"
down_revision = "20260301_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "chat_message_logs" in inspector.get_table_names():
        return

    op.create_table(
        "chat_message_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_message_session_created",
        "chat_message_logs",
        ["session_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "chat_message_logs" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("chat_message_logs")}
    if "ix_chat_message_session_created" in indexes:
        op.drop_index("ix_chat_message_session_created", table_name="chat_message_logs")
    op.drop_table("chat_message_logs")
