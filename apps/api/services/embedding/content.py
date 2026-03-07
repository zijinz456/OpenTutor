"""Batch embedding for content tree nodes.

Called after ingestion to pre-compute vector embeddings
for hybrid search.
"""

import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from services.embedding.registry import get_embedding_provider

logger = logging.getLogger(__name__)

BATCH_SIZE = 200


async def embed_course_content(db: AsyncSession, course_id: uuid.UUID) -> int:
    """Pre-compute embeddings for all un-embedded content tree nodes in a course.

    Returns the number of nodes embedded.
    """
    result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.embedding.is_(None),
            CourseContentTree.content.isnot(None),
        )
    )
    nodes = result.scalars().all()

    if not nodes:
        return 0

    try:
        provider = get_embedding_provider()
    except RuntimeError as e:
        logger.debug(f"Skipping content embedding: {e}")
        return 0

    count = 0
    for i in range(0, len(nodes), BATCH_SIZE):
        batch = nodes[i : i + BATCH_SIZE]
        texts = [f"{n.title}\n{n.content}" for n in batch]

        try:
            embeddings = await provider.embed_batch(texts)
            for node, emb in zip(batch, embeddings):
                node.embedding = emb
                count += 1
        except Exception as e:
            logger.exception("Batch embedding failed for course %s", course_id)
            continue

    await db.flush()
    logger.info(f"Embedded {count} content nodes for course {course_id}")
    return count
