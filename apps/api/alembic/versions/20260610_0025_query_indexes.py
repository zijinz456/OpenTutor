"""Add composite indexes for frequently-queried columns.

- conversation_memories (user_id, course_id, created_at): recency-ordered
  memory lookups stop full-scanning past 10K records.
- practice_results (user_id, problem_id): per-user answer history for a
  problem (mastery and wrong-answer queries).

SQLite local mode gets its schema (including these model-level indexes)
from create_all() at startup — env.py skips Alembic for sqlite URLs — so
this migration only executes on Postgres.

Revision ID: 20260610_0025
Revises: 2870051cd576
Create Date: 2026-06-10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260610_0025"
down_revision = "2870051cd576"
branch_labels = None
depends_on = None


INDEXES = [
    ("conversation_memories", "ix_mem_user_course_created", ["user_id", "course_id", "created_at"]),
    ("practice_results", "ix_practice_result_user_problem", ["user_id", "problem_id"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, index_name, columns in INDEXES:
        if table not in tables:
            continue
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if index_name not in existing:
            op.create_index(index_name, table, columns, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table, index_name, _columns in INDEXES:
        if table not in tables:
            continue
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if index_name in existing:
            op.drop_index(index_name, table_name=table)
