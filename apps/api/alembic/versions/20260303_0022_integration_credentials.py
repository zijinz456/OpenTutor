"""Add integration_credentials table for OAuth2 tokens (Google Calendar, Notion, etc).

Revision ID: 0022_integration_credentials
Revises: 0021_reports
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_integration_credentials"
down_revision = "0021_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "integration_credentials" in inspector.get_table_names():
        return

    op.create_table(
        "integration_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("integration_name", sa.String(50), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.JSONB(), nullable=True),
        sa.Column("extra_data", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "integration_name", name="uq_user_integration"),
    )
    op.create_index("ix_integration_cred_user", "integration_credentials", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "integration_credentials" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("integration_credentials")}
    if "ix_integration_cred_user" in indexes:
        op.drop_index("ix_integration_cred_user", table_name="integration_credentials")
    op.drop_table("integration_credentials")
