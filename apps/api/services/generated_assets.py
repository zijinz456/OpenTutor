"""Shared versioning helpers for generated notes, plans, and flashcards."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.generated_asset import GeneratedAsset


async def save_generated_asset(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    asset_type: str,
    title: str,
    content: dict,
    metadata: dict | None = None,
    replace_batch_id: uuid.UUID | None = None,
) -> dict:
    next_version = 1
    batch_id = replace_batch_id or uuid.uuid4()

    if replace_batch_id:
        result = await db.execute(
            select(GeneratedAsset).where(
                GeneratedAsset.user_id == user_id,
                GeneratedAsset.course_id == course_id,
                GeneratedAsset.asset_type == asset_type,
                GeneratedAsset.batch_id == replace_batch_id,
                GeneratedAsset.is_archived == False,
            )
        )
        existing = result.scalars().all()
        if not existing:
            raise ValueError("Generated asset batch not found")
        next_version = max(asset.version for asset in existing) + 1
        for asset in existing:
            asset.is_archived = True

    asset = GeneratedAsset(
        user_id=user_id,
        course_id=course_id,
        asset_type=asset_type,
        title=title,
        content=content,
        metadata_=metadata,
        batch_id=batch_id,
        version=next_version,
    )
    db.add(asset)
    await db.flush()
    return {
        "id": str(asset.id),
        "batch_id": str(batch_id),
        "version": next_version,
        "replaced": bool(replace_batch_id),
    }


async def list_generated_asset_batches(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    asset_type: str,
) -> list[dict]:
    result = await db.execute(
        select(GeneratedAsset)
        .where(
            GeneratedAsset.user_id == user_id,
            GeneratedAsset.course_id == course_id,
            GeneratedAsset.asset_type == asset_type,
        )
        .order_by(GeneratedAsset.batch_id, GeneratedAsset.version.desc(), GeneratedAsset.created_at.desc())
    )
    rows = result.scalars().all()
    batches: dict[str, dict] = {}
    for asset in rows:
        batch_id = str(asset.batch_id)
        batch = batches.get(batch_id)
        if not batch:
            batches[batch_id] = {
                "batch_id": batch_id,
                "title": asset.title,
                "current_version": asset.version,
                "is_active": not asset.is_archived,
                "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
                "asset_count": 0,
                "preview": asset.content,
            }
            batch = batches[batch_id]
        if asset.version == batch["current_version"]:
            batch["asset_count"] += 1
            batch["is_active"] = batch["is_active"] or (not asset.is_archived)
    return sorted(batches.values(), key=lambda item: (item["is_active"], item["updated_at"] or ""), reverse=True)
