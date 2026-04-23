"""learning paths + path rooms tables + practice_problems.path_room_id

Revision ID: 20260423_0003
Revises: 20260423_0002
Create Date: 2026-04-23

Phase 16a T1 — Python Paths UI. One migration adds the two new tables
and the two nullable columns on ``practice_problems`` that make cards
addressable by room. No ``user_path_progress`` table on purpose: path
progress is **derived** from ``PracticeResult`` rows to avoid dual
accounting (critic C5).

Critic C10 — ``ALTER TABLE practice_problems ADD COLUMN`` on the 581-row
table is metadata-only on Postgres 11+ because both columns are nullable
with no default. On SQLite we use ``batch_alter_table`` so the columns
are added via the ``CREATE TABLE … SELECT`` rewrite path; SQLite cannot
``ALTER TABLE ADD COLUMN`` a column with a foreign-key reference
directly. The migration produces the same logical schema on both.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from models.compat import CompatUUID


revision = "20260423_0003"
down_revision = "20260423_0002"
branch_labels = None
depends_on = None


def _uuid_type():
    """Native UUID on Postgres, ``CompatUUID`` (VARCHAR(36)) on SQLite.

    Mirrors the ORM's cross-dialect type so the migration compiles on
    both the CI SQLite validation backend and the production Postgres
    target.
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return CompatUUID()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    uuid_t = _uuid_type()

    if "learning_paths" not in tables:
        op.create_table(
            "learning_paths",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("slug", sa.String(length=60), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("difficulty", sa.String(length=20), nullable=False),
            sa.Column("track_id", sa.String(length=60), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "room_count_target",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_learning_paths_slug"),
        )
        op.create_index(
            "ix_learning_paths_slug", "learning_paths", ["slug"], unique=False
        )
        op.create_index(
            "ix_learning_paths_track_id",
            "learning_paths",
            ["track_id"],
            unique=False,
        )

    if "path_rooms" not in tables:
        op.create_table(
            "path_rooms",
            sa.Column("id", uuid_t, nullable=False),
            sa.Column("path_id", uuid_t, nullable=False),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("room_order", sa.Integer(), nullable=False),
            sa.Column("intro_excerpt", sa.Text(), nullable=True),
            sa.Column(
                "task_count_target",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["path_id"], ["learning_paths.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("path_id", "slug", name="uq_path_room_slug_per_path"),
            sa.UniqueConstraint(
                "path_id", "room_order", name="uq_path_room_order_per_path"
            ),
        )
        op.create_index("ix_path_rooms_path", "path_rooms", ["path_id"], unique=False)

    # C10 — add the two nullable columns on ``practice_problems``. Both
    # are nullable with no default so Postgres treats each ALTER as a
    # metadata-only write even on the 581-row table. We add the column
    # without an inline FK first, then attach the FK constraint with an
    # explicit name via ``create_foreign_key`` — ``batch_alter_table``
    # refuses unnamed constraints and inline ``ForeignKey(...)`` on
    # ``add_column`` produces an anonymous one.
    practice_columns = {
        col["name"] for col in inspector.get_columns("practice_problems")
    }
    if "path_room_id" not in practice_columns:
        op.add_column(
            "practice_problems",
            sa.Column("path_room_id", uuid_t, nullable=True),
        )
        with op.batch_alter_table("practice_problems") as batch:
            batch.create_foreign_key(
                "fk_practice_problems_path_room_id",
                "path_rooms",
                ["path_room_id"],
                ["id"],
                ondelete="SET NULL",
            )
    if "task_order" not in practice_columns:
        op.add_column(
            "practice_problems",
            sa.Column("task_order", sa.Integer(), nullable=True),
        )

    # Refresh inspector — the add_column above may have rebuilt the
    # table on SQLite; existing index list is still valid since batch
    # preserves indexes.
    inspector = sa.inspect(bind)
    practice_indexes = {
        idx["name"] for idx in inspector.get_indexes("practice_problems")
    }
    if "ix_practice_problem_path_room" not in practice_indexes:
        op.create_index(
            "ix_practice_problem_path_room",
            "practice_problems",
            ["path_room_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "practice_problems" in tables:
        practice_indexes = {
            idx["name"] for idx in inspector.get_indexes("practice_problems")
        }
        if "ix_practice_problem_path_room" in practice_indexes:
            op.drop_index(
                "ix_practice_problem_path_room", table_name="practice_problems"
            )
        practice_columns = {
            col["name"] for col in inspector.get_columns("practice_problems")
        }
        fk_names = {
            fk["name"] for fk in inspector.get_foreign_keys("practice_problems")
        }
        if "path_room_id" in practice_columns:
            # Drop the named FK first so ``batch_alter_table`` does not
            # complain about an unnamed constraint when rewriting the
            # table on SQLite.
            with op.batch_alter_table("practice_problems") as batch:
                if "fk_practice_problems_path_room_id" in fk_names:
                    batch.drop_constraint(
                        "fk_practice_problems_path_room_id",
                        type_="foreignkey",
                    )
                batch.drop_column("path_room_id")
        if "task_order" in practice_columns:
            with op.batch_alter_table("practice_problems") as batch:
                batch.drop_column("task_order")

    if "path_rooms" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("path_rooms")}
        if "ix_path_rooms_path" in indexes:
            op.drop_index("ix_path_rooms_path", table_name="path_rooms")
        op.drop_table("path_rooms")

    if "learning_paths" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("learning_paths")}
        if "ix_learning_paths_track_id" in indexes:
            op.drop_index("ix_learning_paths_track_id", table_name="learning_paths")
        if "ix_learning_paths_slug" in indexes:
            op.drop_index("ix_learning_paths_slug", table_name="learning_paths")
        op.drop_table("learning_paths")
