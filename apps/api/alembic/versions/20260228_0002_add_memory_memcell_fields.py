"""Add MemCell fields to conversation_memories: category, search_vector, indexes.

Supports the upgraded memory system with:
- category: memU 3-layer hierarchy (Resource → Item → Category)
- search_vector: PostgreSQL tsvector for BM25 hybrid search (OpenClaw pattern)
- Indexes for efficient user+type and user+course queries

Revision ID: 20260228_0002
Revises: 20260227_0001
Create Date: 2026-02-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR


# revision identifiers, used by Alembic.
revision = "20260228_0002"
down_revision = "20260227_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Check if table exists
    if "conversation_memories" not in inspector.get_table_names():
        return

    columns = {c["name"] for c in inspector.get_columns("conversation_memories")}

    # Add category column (memU pattern)
    if "category" not in columns:
        op.add_column(
            "conversation_memories",
            sa.Column("category", sa.String(length=100), nullable=True),
        )

    # Add search_vector column (BM25 hybrid search)
    if "search_vector" not in columns:
        op.add_column(
            "conversation_memories",
            sa.Column("search_vector", TSVECTOR, nullable=True),
        )

    # Create indexes
    indexes = {idx["name"] for idx in inspector.get_indexes("conversation_memories")}

    if "ix_mem_user_type" not in indexes:
        op.create_index("ix_mem_user_type", "conversation_memories", ["user_id", "memory_type"])

    if "ix_mem_user_course" not in indexes:
        op.create_index("ix_mem_user_course", "conversation_memories", ["user_id", "course_id"])

    if "ix_mem_search_vector" not in indexes:
        op.create_index(
            "ix_mem_search_vector",
            "conversation_memories",
            ["search_vector"],
            postgresql_using="gin",
        )

    # Backfill search_vector for existing memories
    op.execute("""
        UPDATE conversation_memories
        SET search_vector = to_tsvector('simple', summary)
        WHERE search_vector IS NULL AND summary IS NOT NULL
    """)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "conversation_memories" not in inspector.get_table_names():
        return

    indexes = {idx["name"] for idx in inspector.get_indexes("conversation_memories")}
    if "ix_mem_search_vector" in indexes:
        op.drop_index("ix_mem_search_vector", table_name="conversation_memories")
    if "ix_mem_user_course" in indexes:
        op.drop_index("ix_mem_user_course", table_name="conversation_memories")
    if "ix_mem_user_type" in indexes:
        op.drop_index("ix_mem_user_type", table_name="conversation_memories")

    columns = {c["name"] for c in inspector.get_columns("conversation_memories")}
    if "search_vector" in columns:
        op.drop_column("conversation_memories", "search_vector")
    if "category" in columns:
        op.drop_column("conversation_memories", "category")
