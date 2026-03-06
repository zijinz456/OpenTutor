"""Content mutation service — snapshot, record, restore, and update content nodes.

All content modifications (by agents or users) flow through these functions
to ensure snapshots are created, mutations are audited, and search indexes
are kept in sync.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.content_snapshot import ContentSnapshot
from models.content_mutation import ContentMutation
from services.content.block_utils import extract_text_from_blocks

logger = logging.getLogger(__name__)

# Retention limits
MAX_SNAPSHOTS_PER_NODE = 20
MAX_AUTO_SNAPSHOTS_PER_NODE = 10


async def save_snapshot(
    db: AsyncSession,
    node_id: uuid.UUID,
    snapshot_type: str = "auto",
    label: str | None = None,
) -> ContentSnapshot:
    """Save a snapshot of the current node state before mutation.

    Args:
        node_id: The content node to snapshot.
        snapshot_type: auto | manual | before_regenerate | before_agent_update | before_restore
        label: Optional user-readable label (e.g. "期中复习版本").
    """
    node = await db.get(CourseContentTree, node_id)
    if not node:
        raise ValueError(f"Content node {node_id} not found")

    snapshot = ContentSnapshot(
        node_id=node_id,
        blocks_json=node.blocks_json,
        content_text=node.content,
        snapshot_type=snapshot_type,
        label=label,
    )
    db.add(snapshot)
    await db.flush()

    await enforce_snapshot_retention(db, node_id)
    logger.info("Snapshot created: node=%s type=%s id=%s", node_id, snapshot_type, snapshot.id)
    return snapshot


async def enforce_snapshot_retention(
    db: AsyncSession,
    node_id: uuid.UUID,
    max_total: int = MAX_SNAPSHOTS_PER_NODE,
    max_auto: int = MAX_AUTO_SNAPSHOTS_PER_NODE,
) -> int:
    """Delete oldest snapshots to stay within retention limits.

    Returns the number of snapshots deleted.
    """
    deleted = 0

    # Clean up excess auto snapshots
    auto_result = await db.execute(
        select(ContentSnapshot)
        .where(ContentSnapshot.node_id == node_id, ContentSnapshot.snapshot_type == "auto")
        .order_by(ContentSnapshot.created_at.desc())
    )
    auto_snapshots = auto_result.scalars().all()
    if len(auto_snapshots) > max_auto:
        for snap in auto_snapshots[max_auto:]:
            await db.delete(snap)
            deleted += 1

    # Clean up excess total snapshots
    total_result = await db.execute(
        select(ContentSnapshot)
        .where(ContentSnapshot.node_id == node_id)
        .order_by(ContentSnapshot.created_at.desc())
    )
    all_snapshots = total_result.scalars().all()
    if len(all_snapshots) > max_total:
        for snap in all_snapshots[max_total:]:
            await db.delete(snap)
            deleted += 1

    if deleted:
        await db.flush()
        logger.info("Cleaned %d old snapshots for node %s", deleted, node_id)

    return deleted


async def record_mutation(
    db: AsyncSession,
    node_id: uuid.UUID,
    mutation_type: str,
    reason: str | None = None,
    diff_summary: str | None = None,
    snapshot_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    agent_name: str | None = None,
) -> ContentMutation:
    """Record a mutation in the audit log."""
    mutation = ContentMutation(
        node_id=node_id,
        user_id=user_id,
        agent_name=agent_name,
        mutation_type=mutation_type,
        reason=reason,
        diff_summary=diff_summary,
        snapshot_id=snapshot_id,
    )
    db.add(mutation)
    await db.flush()
    logger.info(
        "Mutation recorded: node=%s type=%s agent=%s",
        node_id, mutation_type, agent_name,
    )
    return mutation


async def restore_snapshot(
    db: AsyncSession,
    node_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> CourseContentTree:
    """Restore a content node to a previous snapshot state.

    Creates a new snapshot of the current state before restoring.
    """
    node = await db.get(CourseContentTree, node_id)
    if not node:
        raise ValueError(f"Content node {node_id} not found")

    snapshot = await db.get(ContentSnapshot, snapshot_id)
    if not snapshot or snapshot.node_id != node_id:
        raise ValueError(f"Snapshot {snapshot_id} not found for node {node_id}")

    # Save current state before overwriting
    pre_restore = await save_snapshot(db, node_id, snapshot_type="before_restore")

    # Apply snapshot
    node.blocks_json = snapshot.blocks_json
    node.content = snapshot.content_text or (
        extract_text_from_blocks(snapshot.blocks_json) if snapshot.blocks_json else None
    )

    # Re-index search vector
    await _reindex_search_vector(db, node)

    # Record the restore mutation
    await record_mutation(
        db, node_id,
        mutation_type="restore",
        reason=f"Restored to snapshot from {snapshot.created_at.isoformat()}",
        snapshot_id=pre_restore.id,
        user_id=user_id,
    )

    await db.flush()
    return node


async def update_node_blocks(
    db: AsyncSession,
    node: CourseContentTree,
    new_blocks: list[dict],
) -> None:
    """Update a node's blocks_json and re-extract content for search indexing."""
    node.blocks_json = new_blocks
    node.content = extract_text_from_blocks(new_blocks)
    await _reindex_search_vector(db, node)
    await db.flush()


async def _reindex_search_vector(db: AsyncSession, node: CourseContentTree) -> None:
    """Re-index the search vector for a content node."""
    try:
        from services.search.indexer import index_content_nodes
        await index_content_nodes(db, [str(node.id)])
    except Exception as e:
        # Non-fatal: search may be slightly stale
        logger.warning("Failed to re-index search vector for node %s: %s", node.id, e)


async def list_snapshots(
    db: AsyncSession,
    node_id: uuid.UUID,
    limit: int = 20,
) -> list[ContentSnapshot]:
    """List snapshots for a content node, newest first."""
    result = await db.execute(
        select(ContentSnapshot)
        .where(ContentSnapshot.node_id == node_id)
        .order_by(ContentSnapshot.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def list_mutations(
    db: AsyncSession,
    node_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[ContentMutation]:
    """List mutations, newest first. Filter by node or course."""
    query = select(ContentMutation).order_by(ContentMutation.created_at.desc()).limit(limit)

    if node_id:
        query = query.where(ContentMutation.node_id == node_id)
    elif course_id:
        # Join through content tree to filter by course
        query = query.join(
            CourseContentTree, ContentMutation.node_id == CourseContentTree.id
        ).where(CourseContentTree.course_id == course_id)

    result = await db.execute(query)
    return list(result.scalars().all())
