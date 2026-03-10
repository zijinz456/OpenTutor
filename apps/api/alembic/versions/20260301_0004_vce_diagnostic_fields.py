"""VCE diagnostic system fields.

Add structured annotation fields for diagnostic features:
- PracticeProblem: difficulty_layer, problem_metadata, parent_problem_id, is_diagnostic
- PracticeResult: error_category, difficulty_layer
- WrongAnswer: diagnosis, error_detail
- LearningProgress: gap_type

Revision ID: 20260301_0004
Revises: 20260228_0003
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "20260301_0004"
down_revision = "20260228_0003"
branch_labels = None
depends_on = None


def _add_column_if_not_exists(table: str, column_name: str, column_type, **kw):
    """Helper to add a column only if it doesn't already exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = [c["name"] for c in inspector.get_columns(table)]
    if column_name not in existing:
        op.add_column(table, sa.Column(column_name, column_type, **kw))


def upgrade() -> None:
    # ── PracticeProblem: structured annotation fields ──
    _add_column_if_not_exists(
        "practice_problems", "difficulty_layer",
        sa.Integer(), nullable=True,
    )
    _add_column_if_not_exists(
        "practice_problems", "problem_metadata",
        JSONB(), nullable=True,
    )
    _add_column_if_not_exists(
        "practice_problems", "parent_problem_id",
        UUID(as_uuid=True),
        nullable=True,
    )
    _add_column_if_not_exists(
        "practice_problems", "is_diagnostic",
        sa.Boolean(), server_default=sa.text("false"), nullable=False,
    )

    # ── PracticeResult: error tracking fields ──
    _add_column_if_not_exists(
        "practice_results", "error_category",
        sa.String(30), nullable=True,
    )
    _add_column_if_not_exists(
        "practice_results", "difficulty_layer",
        sa.Integer(), nullable=True,
    )

    # ── WrongAnswer: diagnosis fields ──
    _add_column_if_not_exists(
        "wrong_answers", "diagnosis",
        sa.String(30), nullable=True,
    )
    _add_column_if_not_exists(
        "wrong_answers", "error_detail",
        JSONB(), nullable=True,
    )

    # ── LearningProgress: gap type ──
    _add_column_if_not_exists(
        "learning_progress", "gap_type",
        sa.String(30), nullable=True,
    )

    # ── Foreign key for parent_problem_id ──
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_fks = [
        fk["name"]
        for fk in inspector.get_foreign_keys("practice_problems")
        if fk.get("name")
    ]
    if "fk_practice_problems_parent" not in existing_fks:
        try:
            op.create_foreign_key(
                "fk_practice_problems_parent",
                "practice_problems",
                "practice_problems",
                ["parent_problem_id"],
                ["id"],
            )
        except (sa.exc.IntegrityError, sa.exc.OperationalError, sa.exc.ProgrammingError):
            pass  # FK may already exist without a name — safe to ignore in migration


def downgrade() -> None:
    op.drop_constraint("fk_practice_problems_parent", "practice_problems", type_="foreignkey")
    op.drop_column("learning_progress", "gap_type")
    op.drop_column("wrong_answers", "error_detail")
    op.drop_column("wrong_answers", "diagnosis")
    op.drop_column("practice_results", "difficulty_layer")
    op.drop_column("practice_results", "error_category")
    op.drop_column("practice_problems", "is_diagnostic")
    op.drop_column("practice_problems", "parent_problem_id")
    op.drop_column("practice_problems", "problem_metadata")
    op.drop_column("practice_problems", "difficulty_layer")
