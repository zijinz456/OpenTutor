"""Full-text search indexer for content tree nodes.

PostgreSQL: Generates tsvector columns for BM25-style ranking via ts_rank_cd.
SQLite: No-op (LIKE-based fallback in hybrid.py is used instead).
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import is_sqlite

logger = logging.getLogger(__name__)


async def index_content_nodes(db: AsyncSession, node_ids: list[str]) -> int:
    """Generate tsvector for content tree nodes.

    Title gets weight 'A' (highest), content gets weight 'B'.
    Uses 'simple' text search config for cross-language compatibility.

    On SQLite this is a no-op — keyword search falls back to LIKE matching.
    """
    if not node_ids:
        return 0

    if is_sqlite():
        return 0

    result = await db.execute(
        text("""
            UPDATE course_content_tree
            SET search_vector =
                setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(content, '')), 'B')
            WHERE id = ANY(:ids)
        """),
        {"ids": node_ids},
    )
    return result.rowcount


async def backfill_search_vectors(db: AsyncSession) -> int:
    """Backfill tsvector for all content nodes that haven't been indexed.

    On SQLite this is a no-op.
    """
    if is_sqlite():
        return 0

    result = await db.execute(
        text("""
            UPDATE course_content_tree
            SET search_vector =
                setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('simple', coalesce(content, '')), 'B')
            WHERE search_vector IS NULL AND content IS NOT NULL
            RETURNING id
        """)
    )
    count = result.rowcount
    logger.info(f"Backfilled search vectors for {count} nodes")
    return count
