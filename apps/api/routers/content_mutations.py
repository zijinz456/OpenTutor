"""Content mutation endpoints — snapshots, mutations, lock/unlock, block editing."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from schemas.content_mutation import (
    SnapshotResponse,
    MutationResponse,
    SaveBlocksRequest,
    ContentNodeResponse,
)

router = APIRouter(tags=["content-mutations"])


@router.get("/{node_id}/snapshots", response_model=list[SnapshotResponse])
async def list_snapshots_endpoint(
    node_id: uuid.UUID,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List snapshots for a content node, newest first."""
    from services.content.mutations import list_snapshots

    snapshots = await list_snapshots(db, node_id, limit=limit)
    return [
        SnapshotResponse(
            id=s.id,
            node_id=s.node_id,
            snapshot_type=s.snapshot_type,
            label=s.label,
            has_blocks=s.blocks_json is not None,
            has_content=s.content_text is not None,
            created_at=s.created_at,
        )
        for s in snapshots
    ]


@router.post("/{node_id}/restore/{snapshot_id}", response_model=ContentNodeResponse)
async def restore_snapshot_endpoint(
    node_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Restore a content node to a previous snapshot."""
    from services.content.mutations import restore_snapshot

    try:
        node = await restore_snapshot(db, node_id, snapshot_id, user_id=user.id)
        await db.commit()
        return ContentNodeResponse(
            id=node.id,
            title=node.title,
            content=node.content,
            blocks_json=node.blocks_json,
            level=node.level,
            order_index=node.order_index,
            source_type=node.source_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{node_id}/mutations", response_model=list[MutationResponse])
async def list_mutations_endpoint(
    node_id: uuid.UUID,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List agent mutations for a content node (activity feed data)."""
    from services.content.mutations import list_mutations

    mutations = await list_mutations(db, node_id=node_id, limit=limit)
    return [MutationResponse.model_validate(m) for m in mutations]


@router.get("/course/{course_id}/mutations", response_model=list[MutationResponse])
async def list_course_mutations_endpoint(
    course_id: uuid.UUID,
    limit: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all mutations for a course (course-level activity feed)."""
    from services.content.mutations import list_mutations

    mutations = await list_mutations(db, course_id=course_id, limit=limit)
    return [MutationResponse.model_validate(m) for m in mutations]


@router.post("/{node_id}/lock")
async def lock_node_endpoint(
    node_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lock a content node to prevent AI modifications."""
    from models.content import CourseContentTree
    from models.practice import PracticeProblem
    from services.content.block_utils import set_all_blocks_locked
    from services.content.mutations import record_mutation
    from sqlalchemy import update

    node = await db.get(CourseContentTree, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Content node not found")

    if node.blocks_json:
        node.blocks_json = set_all_blocks_locked(node.blocks_json, True)

    await db.execute(
        update(PracticeProblem)
        .where(PracticeProblem.content_node_id == node_id)
        .values(locked=True)
    )

    await record_mutation(db, node_id, mutation_type="lock", user_id=user.id)
    await db.commit()
    return {"status": "locked", "node_id": str(node_id)}


@router.post("/{node_id}/unlock")
async def unlock_node_endpoint(
    node_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unlock a content node to allow AI modifications."""
    from models.content import CourseContentTree
    from models.practice import PracticeProblem
    from services.content.block_utils import set_all_blocks_locked
    from services.content.mutations import record_mutation
    from sqlalchemy import update

    node = await db.get(CourseContentTree, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Content node not found")

    if node.blocks_json:
        node.blocks_json = set_all_blocks_locked(node.blocks_json, False)

    await db.execute(
        update(PracticeProblem)
        .where(PracticeProblem.content_node_id == node_id)
        .values(locked=False)
    )

    await record_mutation(db, node_id, mutation_type="unlock", user_id=user.id)
    await db.commit()
    return {"status": "unlocked", "node_id": str(node_id)}


@router.put("/{node_id}/blocks", response_model=ContentNodeResponse)
async def save_blocks_endpoint(
    node_id: uuid.UUID,
    body: SaveBlocksRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save user edits to blocks_json. Creates auto snapshot first."""
    from models.content import CourseContentTree
    from services.content.mutations import save_snapshot, record_mutation, update_node_blocks
    from services.content.block_utils import ensure_block_metadata

    node = await db.get(CourseContentTree, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Content node not found")

    # Save snapshot before user edit
    await save_snapshot(
        db, node_id,
        snapshot_type="auto",
        label=body.snapshot_label,
    )

    # Mark any modified AI blocks as user_edited
    blocks = body.blocks
    for block in blocks:
        block = ensure_block_metadata(block)
        # If block was AI-generated and now being saved by user, mark as edited
        if block["metadata"].get("owner") == "ai" and not block["metadata"].get("locked"):
            block["metadata"]["owner"] = "ai+user_edited"

    await update_node_blocks(db, node, blocks)

    await record_mutation(
        db, node_id,
        mutation_type="user_edit",
        user_id=user.id,
    )
    await db.commit()

    return ContentNodeResponse(
        id=node.id,
        title=node.title,
        content=node.content,
        blocks_json=node.blocks_json,
        level=node.level,
        order_index=node.order_index,
        source_type=node.source_type,
    )
