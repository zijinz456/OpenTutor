"""drills domain tables — Phase 16c T1+T4

Revision ID: 20260425_0002
Revises: 20260425_0001
Create Date: 2026-04-25

Practice-first pivot. Four new tables (``drill_courses`` → ``drill_modules``
→ ``drills`` + ``drill_attempts``) parallel the existing
``learning_paths`` / ``path_rooms`` structure but are owned by the drills
domain, not the flashcard domain. Separate tables keep the two product
surfaces decoupled while the pivot lands.

``reference_solution`` intentionally omitted per critic C3 — lives in
source YAML only, never in the DB.
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from models.compat import CompatUUID


revision: str = "20260425_0002"
down_revision: str = "20260425_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_type():
    """Native UUID on Postgres, ``CompatUUID`` (VARCHAR(36)) on SQLite."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return CompatUUID()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    uuid_t = _uuid_type()

    if "drill_courses" not in tables:
        op.create_table(
            "drill_courses",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("slug", sa.String(length=60), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("source", sa.String(length=40), nullable=False),
            sa.Column("version", sa.String(length=20), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("estimated_hours", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_drill_courses_slug"),
        )
        op.create_index(
            "ix_drill_courses_slug", "drill_courses", ["slug"], unique=False
        )

    if "drill_modules" not in tables:
        op.create_table(
            "drill_modules",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("course_id", uuid_t, nullable=False),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("outcome", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["course_id"], ["drill_courses.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "course_id", "slug", name="uq_drill_modules_course_slug"
            ),
            sa.UniqueConstraint(
                "course_id", "order_index", name="uq_drill_modules_course_order"
            ),
        )
        op.create_index(
            "ix_drill_modules_course", "drill_modules", ["course_id"], unique=False
        )

    if "drills" not in tables:
        op.create_table(
            "drills",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("module_id", uuid_t, nullable=False),
            sa.Column("slug", sa.String(length=100), nullable=False),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=250), nullable=False),
            sa.Column("why_it_matters", sa.String(length=500), nullable=False),
            sa.Column("starter_code", sa.Text(), nullable=False),
            sa.Column("hidden_tests", sa.Text(), nullable=False),
            sa.Column(
                "hints",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column(
                "skill_tags",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
            sa.Column("source_citation", sa.String(length=300), nullable=False),
            sa.Column(
                "time_budget_min",
                sa.Integer(),
                nullable=False,
                server_default="10",
            ),
            sa.Column(
                "difficulty_layer",
                sa.SmallInteger(),
                nullable=False,
                server_default="1",
            ),
            sa.ForeignKeyConstraint(
                ["module_id"], ["drill_modules.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("module_id", "slug", name="uq_drills_module_slug"),
            sa.CheckConstraint(
                "difficulty_layer BETWEEN 1 AND 3",
                name="ck_drills_difficulty_range",
            ),
        )
        op.create_index(
            "ix_drills_module_order",
            "drills",
            ["module_id", "order_index"],
            unique=False,
        )

    if "drill_attempts" not in tables:
        op.create_table(
            "drill_attempts",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("user_id", uuid_t, nullable=False),
            sa.Column("drill_id", uuid_t, nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
            sa.Column("submitted_code", sa.Text(), nullable=False),
            sa.Column("runner_output", sa.Text(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column(
                "attempted_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["drill_id"], ["drills.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_drill_attempts_user_time",
            "drill_attempts",
            ["user_id", sa.text("attempted_at DESC")],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "drill_attempts" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("drill_attempts")}
        if "ix_drill_attempts_user_time" in indexes:
            op.drop_index("ix_drill_attempts_user_time", table_name="drill_attempts")
        op.drop_table("drill_attempts")

    if "drills" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("drills")}
        if "ix_drills_module_order" in indexes:
            op.drop_index("ix_drills_module_order", table_name="drills")
        op.drop_table("drills")

    if "drill_modules" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("drill_modules")}
        if "ix_drill_modules_course" in indexes:
            op.drop_index("ix_drill_modules_course", table_name="drill_modules")
        op.drop_table("drill_modules")

    if "drill_courses" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("drill_courses")}
        if "ix_drill_courses_slug" in indexes:
            op.drop_index("ix_drill_courses_slug", table_name="drill_courses")
        op.drop_table("drill_courses")
