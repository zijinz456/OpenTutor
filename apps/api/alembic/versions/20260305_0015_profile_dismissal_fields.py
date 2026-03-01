"""Add dismissal fields for preferences, signals, and memories.

Revision ID: 20260305_0015
Revises: 20260304_0014
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_0015"
down_revision = "20260304_0014"
branch_labels = None
depends_on = None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if table_name not in tables:
        return
    columns = {col["name"] for col in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column_if_missing("user_preferences", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("user_preferences", sa.Column("dismissal_reason", sa.Text(), nullable=True))
    _add_column_if_missing("preference_signals", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("preference_signals", sa.Column("dismissal_reason", sa.Text(), nullable=True))
    _add_column_if_missing("conversation_memories", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_if_missing("conversation_memories", sa.Column("dismissal_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name in ("conversation_memories", "preference_signals", "user_preferences"):
        if table_name not in set(inspector.get_table_names()):
            continue
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        if "dismissal_reason" in columns:
            op.drop_column(table_name, "dismissal_reason")
        if "dismissed_at" in columns:
            op.drop_column(table_name, "dismissed_at")
