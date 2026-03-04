"""Cross-database search compatibility helpers.

Wraps PostgreSQL-specific full-text search operations so they become
no-ops on SQLite (where LIKE-based fallback is used instead).
"""

import math

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import is_sqlite


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


async def update_search_vector(
    db: AsyncSession,
    table: str,
    record_id: str,
    summary: str,
) -> None:
    """Update the tsvector search_vector column for a record.

    PostgreSQL: Runs to_tsvector('simple', ...) to populate the column.
    SQLite: No-op — keyword search uses LIKE fallback.
    """
    if is_sqlite():
        return

    await db.execute(
        text(f"""
            UPDATE {table}
            SET search_vector = to_tsvector('simple', :summary)
            WHERE id = :id
        """),
        {"summary": summary, "id": record_id},
    )


async def fulltext_search_memories(
    db: AsyncSession,
    user_id: str,
    query: str,
    *,
    course_id: str | None = None,
    memory_types: list[str] | None = None,
    limit: int = 20,
) -> list:
    """Search conversation_memories using full-text search (PG) or LIKE (SQLite)."""
    params: dict = {"user_id": user_id, "query": query, "limit": limit}

    if is_sqlite():
        # SQLite LIKE-based fallback
        filters = [
            "user_id = :user_id",
            "dismissed_at IS NULL",
            "(summary LIKE '%' || :query || '%')",
        ]
        if course_id:
            filters.append("course_id = :course_id")
            params["course_id"] = course_id
        if memory_types:
            placeholders = ", ".join(f":mt{i}" for i in range(len(memory_types)))
            filters.append(f"memory_type IN ({placeholders})")
            for i, mt in enumerate(memory_types):
                params[f"mt{i}"] = mt

        result = await db.execute(
            text(f"""
                SELECT id, summary, memory_type, importance, access_count,
                       created_at, category, 1.0 AS rank
                FROM conversation_memories
                WHERE {" AND ".join(filters)}
                LIMIT :limit
            """),
            params,
        )
        return result.fetchall()

    # PostgreSQL: BM25 via ts_rank_cd
    filters = [
        "user_id = :user_id",
        "search_vector IS NOT NULL",
        "dismissed_at IS NULL",
        "search_vector @@ plainto_tsquery('simple', :query)",
    ]
    if course_id:
        filters.append("course_id = :course_id")
        params["course_id"] = course_id
    if memory_types:
        placeholders = ", ".join(f":mt{i}" for i in range(len(memory_types)))
        filters.append(f"memory_type IN ({placeholders})")
        for i, mt in enumerate(memory_types):
            params[f"mt{i}"] = mt

    result = await db.execute(
        text(f"""
            SELECT id, summary, memory_type, importance, access_count,
                   created_at, category,
                   ts_rank_cd(search_vector, plainto_tsquery('simple', :query), 32) AS rank
            FROM conversation_memories
            WHERE {" AND ".join(filters)}
            ORDER BY rank DESC
            LIMIT :limit
        """),
        params,
    )
    return result.fetchall()
