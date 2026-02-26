"""Full-text search indexer for content tree nodes.

Generates PostgreSQL tsvector columns for BM25-style ranking
via ts_rank_cd. Uses 'simple' config for cross-language support
(English + Chinese).
"""

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def index_content_nodes(db: AsyncSession, node_ids: list[str]) -> int:
    """Generate tsvector for content tree nodes.

    Title gets weight 'A' (highest), content gets weight 'B'.
    Uses 'simple' text search config for cross-language compatibility.
    """
    if not node_ids:
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
    """Backfill tsvector for all content nodes that haven't been indexed."""
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
