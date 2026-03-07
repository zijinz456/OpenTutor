"""SQLite search helpers."""

import math

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
    """Keep call-site compatibility; SQLite mode does not maintain search vectors."""
    _ = (db, table, record_id, summary)
    return None


async def fulltext_search_memories(
    db: AsyncSession,
    user_id: str,
    query: str,
    *,
    course_id: str | None = None,
    memory_types: list[str] | None = None,
    limit: int = 20,
) -> list:
    """Search conversation_memories using LIKE-based matching in SQLite mode."""
    params: dict = {"user_id": user_id, "query": query, "limit": limit}
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
                   created_at, category,
                   1.0 AS rank
            FROM conversation_memories
            WHERE {" AND ".join(filters)}
            LIMIT :limit
        """),
        params,
    )
    return result.fetchall()
