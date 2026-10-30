"""Mastery-ledger restructuring: drop replaced tables, normalize problem sources.

Tables dropped (no SQLAlchemy model any more):
- study_sessions        — never written; study time now comes from
                          learning_progress.time_spent_minutes / practice_results
- learning_templates    — templates are module constants since 20261030_0027
- intervention_outcomes — cognitive-load calibration layer removed
- cognitive_baselines   — cognitive-load calibration layer removed

Data normalization:
- practice_problems.source "generated" -> "ai_generated" (ProblemSource enum:
  extracted | ai_generated | derived | imported)

SQLite local mode gets its schema from create_all() at startup — env.py skips
Alembic for sqlite URLs — so the DDL only executes on Postgres. The downgrade
re-creates the tables with their original shapes; the source rename is kept.

Revision ID: 20261031_0028
Revises: 20261030_0027
Create Date: 2026-10-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261031_0028"
down_revision = "20261030_0027"
branch_labels = None
depends_on = None


DROPPED_TABLES: list[str] = [
    "intervention_outcomes",
    "cognitive_baselines",
    "study_sessions",
    "learning_templates",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "practice_problems" in tables:
        op.execute(
            sa.text("UPDATE practice_problems SET source = 'ai_generated' WHERE source = 'generated'")
        )

    if bind.dialect.name == "sqlite":
        return

    for table in DROPPED_TABLES:
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    uuid_t = postgresql.UUID(as_uuid=True)

    if "study_sessions" not in tables:
        op.create_table(
            "study_sessions",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column("user_id", uuid_t, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_id", uuid_t, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_minutes", sa.Integer(), nullable=True),
            sa.Column("messages_sent", sa.Integer(), server_default="0"),
            sa.Column("problems_attempted", sa.Integer(), server_default="0"),
            sa.Column("problems_correct", sa.Integer(), server_default="0"),
            sa.Column("notes_viewed", sa.Integer(), server_default="0"),
            sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        )

    if "learning_templates" not in tables:
        op.create_table(
            "learning_templates",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_builtin", sa.Boolean(), server_default=sa.false()),
            sa.Column("created_by", uuid_t, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("preferences", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("scene_id", sa.String(50), nullable=True),
            sa.Column("workflow", sa.String(50), nullable=True),
            sa.Column("target_audience", sa.String(100), nullable=True),
            sa.Column("tags", postgresql.JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "intervention_outcomes" not in tables:
        op.create_table(
            "intervention_outcomes",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column("user_id", uuid_t, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_id", uuid_t, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=True),
            sa.Column("intervention_type", sa.String(50), nullable=False),
            sa.Column("block_type", sa.String(50), nullable=False),
            sa.Column("signal_source", sa.String(50), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("cognitive_load_before", sa.Float(), nullable=True),
            sa.Column("cognitive_load_after", sa.Float(), nullable=True),
            sa.Column("was_effective", sa.Boolean(), nullable=True),
            sa.Column("user_feedback", sa.String(20), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(
            "ix_intervention_user_course_time", "intervention_outcomes", ["user_id", "course_id", "created_at"]
        )
        op.create_index("ix_intervention_unresolved", "intervention_outcomes", ["user_id", "resolved_at"])

    if "cognitive_baselines" not in tables:
        op.create_table(
            "cognitive_baselines",
            sa.Column("user_id", uuid_t, primary_key=True),
            sa.Column("avg_message_length", sa.Float(), server_default="0"),
            sa.Column("avg_word_count", sa.Float(), server_default="0"),
            sa.Column("help_seeking_rate", sa.Float(), server_default="0"),
            sa.Column("message_count", sa.Integer(), server_default="0"),
            sa.Column("session_count", sa.Integer(), server_default="0"),
            sa.Column("total_length", sa.Float(), server_default="0"),
            sa.Column("total_words", sa.Float(), server_default="0"),
            sa.Column("help_count", sa.Integer(), server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
