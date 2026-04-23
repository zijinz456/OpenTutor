"""interview sessions and turns tables

Revision ID: 20260423_0001
Revises: 2870051cd576
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from models.compat import CompatJSONB, CompatUUID


revision = "20260423_0001"
down_revision = "2870051cd576"
branch_labels = None
depends_on = None


def _uuid_type():
    """Native UUID on Postgres, ``CompatUUID`` (VARCHAR(36)) on SQLite.

    Mirrors the ORM's cross-dialect type so the migration compiles on both
    the CI SQLite validation backend and the production Postgres target.
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return CompatUUID()


def _jsonb_type():
    """Postgres ``JSONB`` when available, falling back to SQLAlchemy ``JSON``."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return CompatJSONB()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    uuid_t = _uuid_type()
    jsonb_t = _jsonb_type()

    if "interview_sessions" not in tables:
        op.create_table(
            "interview_sessions",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("user_id", uuid_t, nullable=False),
            sa.Column("course_id", uuid_t, nullable=True),
            sa.Column("mode", sa.String(length=30), nullable=False),
            sa.Column("duration", sa.String(length=20), nullable=False),
            sa.Column("project_focus", sa.String(length=60), nullable=False),
            sa.Column("total_turns", sa.Integer(), nullable=False),
            sa.Column(
                "completed_turns",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="in_progress",
            ),
            sa.Column("summary_json", jsonb_t, nullable=True),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_interview_sessions_user_started",
            "interview_sessions",
            ["user_id", "started_at"],
            unique=False,
        )

    if "interview_turns" not in tables:
        op.create_table(
            "interview_turns",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("session_id", uuid_t, nullable=False),
            sa.Column("turn_number", sa.Integer(), nullable=False),
            sa.Column("question_type", sa.String(length=30), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=True),
            sa.Column("rubric_scores_json", jsonb_t, nullable=True),
            sa.Column("rubric_feedback_short", sa.Text(), nullable=True),
            sa.Column("grounding_source", sa.String(length=80), nullable=True),
            sa.Column("llm_model", sa.String(length=60), nullable=True),
            sa.Column("answer_time_ms", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["interview_sessions.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "session_id",
                "turn_number",
                name="uq_interview_turn_session_turn",
            ),
        )
        op.create_index(
            "ix_interview_turns_session_turn",
            "interview_turns",
            ["session_id", "turn_number"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "interview_turns" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("interview_turns")}
        if "ix_interview_turns_session_turn" in indexes:
            op.drop_index(
                "ix_interview_turns_session_turn", table_name="interview_turns"
            )
        op.drop_table("interview_turns")

    if "interview_sessions" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("interview_sessions")}
        if "ix_interview_sessions_user_started" in indexes:
            op.drop_index(
                "ix_interview_sessions_user_started", table_name="interview_sessions"
            )
        op.drop_table("interview_sessions")
