"""Helpers for generating and persisting podcast assets."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.generated_assets import save_generated_asset

logger = logging.getLogger(__name__)


async def generate_and_store_podcast(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    topic: str,
    style: str,
) -> tuple[bytes, list[dict], uuid.UUID | None]:
    """Generate podcast audio and persist its metadata as a generated asset."""
    from services.audio.podcast import generate_study_podcast

    audio_bytes, dialogue = await generate_study_podcast(
        course_id=str(course_id),
        topic=topic,
        db=db,
        style=style,
    )

    asset_id: uuid.UUID | None = None
    try:
        asset = await save_generated_asset(
            db,
            user_id=user_id,
            course_id=course_id,
            asset_type="podcast",
            title=f"Podcast: {topic}",
            content={"dialogue": dialogue},
            metadata={"style": style, "topic": topic, "audio_size": len(audio_bytes)},
        )
        asset_id = asset.id
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to persist podcast asset: %s", exc)

    return audio_bytes, dialogue, asset_id
