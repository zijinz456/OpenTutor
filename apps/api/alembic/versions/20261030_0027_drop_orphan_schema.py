"""Drop orphaned columns and alembic-only tables left behind by removed features.

Columns (no reader or writer anywhere in apps/api):
- course_content_tree.blocks_json
- course_content_tree.search_vector (+ ix_content_tree_search_vector)
- learning_progress.ease_factor (SM-2 legacy; FSRS fields are authoritative)
- ingestion_jobs.user_corrected_category / user_corrected_course
- learning_templates.tab_preset
- study_sessions.signals_extracted

Tables (created by earlier migrations, no SQLAlchemy model and no SQL reference):
- reports, audit_logs, tool_call_events
- study_plans (planner now persists plans only as generated_assets)

SQLite local mode gets its schema from create_all() at startup — env.py skips
Alembic for sqlite URLs — so this migration only executes on Postgres. The
downgrade re-creates the columns/tables with their original shapes.

Revision ID: 20261030_0027
Revises: 20261028_0026
Create Date: 2026-10-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261030_0027"
down_revision = "20261028_0026"
branch_labels = None
depends_on = None


# (table, column)
ORPHAN_COLUMNS: list[tuple[str, str]] = [
    ("course_content_tree", "blocks_json"),
    ("course_content_tree", "search_vector"),
    ("learning_progress", "ease_factor"),
    ("ingestion_jobs", "user_corrected_category"),
    ("ingestion_jobs", "user_corrected_course"),
    ("learning_templates", "tab_preset"),
    ("study_sessions", "signals_extracted"),
]

# (table, index) dropped before the owning column
ORPHAN_INDEXES: list[tuple[str, str]] = [
    ("course_content_tree", "ix_content_tree_search_vector"),
]

ORPHAN_TABLES: list[str] = ["reports", "audit_logs", "tool_call_events", "study_plans"]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, index_name in ORPHAN_INDEXES:
        if table not in tables:
            continue
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table)

    for table, column in ORPHAN_COLUMNS:
        if table not in tables:
            continue
        columns = {col["name"] for col in inspector.get_columns(table)}
        if column in columns:
            op.drop_column(table, column)

    for table in ORPHAN_TABLES:
        if table in tables:
            op.drop_table(table)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    def _columns(table: str) -> set[str]:
        return {col["name"] for col in inspector.get_columns(table)}

    if "course_content_tree" in tables:
        cols = _columns("course_content_tree")
        if "blocks_json" not in cols:
            op.add_column("course_content_tree", sa.Column("blocks_json", postgresql.JSONB(), nullable=True))
        if "search_vector" not in cols:
            op.add_column("course_content_tree", sa.Column("search_vector", postgresql.TSVECTOR(), nullable=True))
            op.create_index(
                "ix_content_tree_search_vector", "course_content_tree", ["search_vector"], postgresql_using="gin"
            )
    if "learning_progress" in tables and "ease_factor" not in _columns("learning_progress"):
        op.add_column("learning_progress", sa.Column("ease_factor", sa.Float(), nullable=True, server_default="2.5"))
    if "ingestion_jobs" in tables:
        cols = _columns("ingestion_jobs")
        if "user_corrected_category" not in cols:
            op.add_column("ingestion_jobs", sa.Column("user_corrected_category", sa.String(50), nullable=True))
        if "user_corrected_course" not in cols:
            op.add_column(
                "ingestion_jobs", sa.Column("user_corrected_course", postgresql.UUID(as_uuid=True), nullable=True)
            )
    if "learning_templates" in tables and "tab_preset" not in _columns("learning_templates"):
        op.add_column("learning_templates", sa.Column("tab_preset", postgresql.JSONB(), nullable=True))
    if "study_sessions" in tables and "signals_extracted" not in _columns("study_sessions"):
        op.add_column(
            "study_sessions", sa.Column("signals_extracted", sa.Integer(), nullable=True, server_default="0")
        )

    if "study_plans" not in tables:
        op.create_table(
            "study_plans",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("scene_id", sa.String(50), nullable=True),
            sa.Column("tasks", postgresql.JSONB(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if "reports" not in tables:
        op.create_table(
            "reports",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("course_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("report_type", sa.String(30), nullable=False),
            sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
            sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("data_snapshot", postgresql.JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_report_user_type_created", "reports", ["user_id", "report_type", "created_at"])

    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("tool_name", sa.String(length=80), nullable=True),
            sa.Column("action_kind", sa.String(length=80), nullable=False),
            sa.Column("approval_status", sa.String(length=20), nullable=True),
            sa.Column("outcome", sa.String(length=40), nullable=False),
            sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["task_id"], ["agent_tasks.id"], ondelete="SET NULL"),
        )
        op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_user_id", "created_at"])
        op.create_index("ix_audit_logs_task_created", "audit_logs", ["task_id", "created_at"])
        op.create_index("ix_audit_logs_action_created", "audit_logs", ["action_kind", "created_at"])

    if "tool_call_events" not in tables:
        op.create_table(
            "tool_call_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("session_id", sa.String(64), nullable=True),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("course_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=True),
            sa.Column("agent_name", sa.String(64), nullable=False),
            sa.Column("tool_name", sa.String(128), nullable=False),
            sa.Column("input_json", postgresql.JSONB(), nullable=True),
            sa.Column("output_text", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="success"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Float(), nullable=True),
            sa.Column("iteration", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_tool_call_user_created", "tool_call_events", ["user_id", "created_at"])
        op.create_index("ix_tool_call_tool_name", "tool_call_events", ["tool_name"])
