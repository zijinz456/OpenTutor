"""Add FSRS spaced repetition fields to learning_progress.

Revision ID: 20260302_0010
Revises: 20260302_0009
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260302_0010"
down_revision = "20260302_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "learning_progress" in tables:
        columns = {col["name"] for col in inspector.get_columns("learning_progress")}
        new_cols = [
            ("fsrs_difficulty", sa.Float(), 5.0),
            ("fsrs_stability", sa.Float(), 0.0),
            ("fsrs_reps", sa.Integer(), 0),
            ("fsrs_lapses", sa.Integer(), 0),
            ("fsrs_state", sa.String(20), "new"),
        ]
        for col_name, col_type, default in new_cols:
            if col_name not in columns:
                op.add_column(
                    "learning_progress",
                    sa.Column(col_name, col_type, nullable=False, server_default=str(default)),
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "learning_progress" in tables:
        columns = {col["name"] for col in inspector.get_columns("learning_progress")}
        for col_name in ["fsrs_difficulty", "fsrs_stability", "fsrs_reps", "fsrs_lapses", "fsrs_state"]:
            if col_name in columns:
                op.drop_column("learning_progress", col_name)
