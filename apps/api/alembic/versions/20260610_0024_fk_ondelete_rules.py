"""Add explicit ondelete rules (CASCADE / SET NULL) to all foreign keys.

Aligns the database with the model-level ForeignKey(..., ondelete=...) audit:
- Child rows owned by a user/course/problem cascade on parent delete.
- Soft references (analytics, derived links, optional classifications) SET NULL.

SQLite local mode is handled by create_all() at startup (env.py skips
migrations for sqlite URLs), so this migration only executes on Postgres.

Revision ID: 20260610_0024
Revises: 2870051cd576
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260610_0024"
down_revision = "2870051cd576"
branch_labels = None
depends_on = None


# (table, column, referenced_table, ondelete)
FK_RULES = [
    # courses owned by users
    ("courses", "user_id", "users", "CASCADE"),
    # content tree nodes belong to a course; subtree dies with its parent node
    ("course_content_tree", "course_id", "courses", "CASCADE"),
    ("course_content_tree", "parent_id", "course_content_tree", "CASCADE"),
    # memories belong to a user; course link is a soft reference
    ("conversation_memories", "user_id", "users", "CASCADE"),
    ("conversation_memories", "course_id", "courses", "SET NULL"),
    # generated assets belong to a user; survive course deletion (issue #36)
    ("generated_assets", "user_id", "users", "CASCADE"),
    ("generated_assets", "course_id", "courses", "SET NULL"),
    # ingestion jobs belong to a user; assignments outlive their source job
    ("ingestion_jobs", "user_id", "users", "CASCADE"),
    ("assignments", "source_ingestion_id", "ingestion_jobs", "SET NULL"),
    # practice problems belong to a course; node/parent links are soft
    ("practice_problems", "course_id", "courses", "CASCADE"),
    ("practice_problems", "content_node_id", "course_content_tree", "SET NULL"),
    ("practice_problems", "parent_problem_id", "practice_problems", "SET NULL"),
    # practice results die with their problem or user
    ("practice_results", "problem_id", "practice_problems", "CASCADE"),
    ("practice_results", "user_id", "users", "CASCADE"),
    # scrape sources belong to user+course; last ingestion link is soft
    ("scrape_sources", "user_id", "users", "CASCADE"),
    ("scrape_sources", "course_id", "courses", "CASCADE"),
    ("scrape_sources", "last_ingestion_id", "ingestion_jobs", "SET NULL"),
    # auth sessions belong to a user
    ("auth_sessions", "user_id", "users", "CASCADE"),
    # study plans belong to user+course
    ("study_plans", "user_id", "users", "CASCADE"),
    ("study_plans", "course_id", "courses", "CASCADE"),
    # usage events: keep per-user cleanup, preserve analytics on course delete
    ("usage_events", "user_id", "users", "CASCADE"),
    ("usage_events", "course_id", "courses", "SET NULL"),
]


def _fk_name(table: str, column: str, ref_table: str) -> str:
    return f"fk_{table}_{column}_{ref_table}"


def _apply_rules(rules, ondelete_for_create) -> None:
    bind = op.get_bind()

    if bind.dialect.name == "sqlite":
        # SQLite local mode gets the schema from Base.metadata.create_all()
        # (env.py skips Alembic for sqlite); altering existing FKs would
        # require a full batch table rebuild for no benefit here.
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, column, ref_table, ondelete in rules:
        if table not in tables or ref_table not in tables:
            continue
        columns = {col["name"] for col in inspector.get_columns(table)}
        if column not in columns:
            continue

        existing_fks = inspector.get_foreign_keys(table)
        for fk in existing_fks:
            if fk.get("constrained_columns") == [column] and fk.get("name"):
                op.drop_constraint(fk["name"], table, type_="foreignkey")

        op.create_foreign_key(
            _fk_name(table, column, ref_table),
            table,
            ref_table,
            [column],
            ["id"],
            ondelete=ondelete_for_create(ondelete),
        )


def upgrade() -> None:
    _apply_rules(FK_RULES, ondelete_for_create=lambda rule: rule)


def downgrade() -> None:
    # Recreate the same foreign keys without ondelete (NO ACTION default).
    _apply_rules(FK_RULES, ondelete_for_create=lambda rule: None)
