"""Search index helpers for SQLite local mode."""

from sqlalchemy.ext.asyncio import AsyncSession


async def index_content_nodes(db: AsyncSession, node_ids: list[str]) -> int:
    """Keep call-site compatibility; SQLite mode uses direct content scanning."""
    _ = db
    if not node_ids:
        return 0
    return 0


async def backfill_search_vectors(db: AsyncSession) -> int:
    """Keep call-site compatibility; SQLite mode does not backfill tsvector."""
    _ = db
    return 0
