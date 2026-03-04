"""Podcast endpoints: generate and list study podcasts.

Provides a dedicated podcast API that generates conversational study podcasts
from course materials and persists metadata via GeneratedAsset.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from database import get_db
from models.generated_asset import GeneratedAsset
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()

ALLOWED_PODCAST_STYLES = {"review", "deep_dive", "exam_prep"}


class PodcastGenerateRequest(BaseModel):
    course_id: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1, max_length=200)
    style: str = "review"

    @field_validator("style")
    @classmethod
    def normalize_style(cls, value: str) -> str:
        return value if value in ALLOWED_PODCAST_STYLES else "review"


@router.post("/generate")
async def generate_podcast(
    body: PodcastGenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate a study podcast for a course topic.

    Returns MP3 audio as a streaming response. The dialogue script is
    persisted as a GeneratedAsset for later retrieval via the list endpoint.
    """
    from services.audio.podcast_assets import generate_and_store_podcast

    try:
        course_uuid = uuid.UUID(body.course_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid course_id format")

    await get_course_or_404(db, course_uuid, user_id=user.id)

    audio_bytes, dialogue, asset_id = await generate_and_store_podcast(
        db=db,
        user_id=user.id,
        course_id=course_uuid,
        topic=body.topic,
        style=body.style,
    )

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="podcast-{body.topic[:30]}.mp3"',
            "X-Podcast-Script": "true",
            "X-Podcast-Lines": str(len(dialogue)),
            "X-Podcast-Asset-Id": str(asset_id) if asset_id else "",
        },
    )


@router.get("/list")
async def list_podcasts(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List generated podcasts for a course.

    Returns podcast metadata from GeneratedAsset records.
    """
    try:
        course_uuid = uuid.UUID(course_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid course_id format")

    await get_course_or_404(db, course_uuid, user_id=user.id)

    result = await db.execute(
        select(GeneratedAsset)
        .where(
            GeneratedAsset.user_id == user.id,
            GeneratedAsset.course_id == course_uuid,
            GeneratedAsset.asset_type == "podcast",
            GeneratedAsset.is_archived == False,  # noqa: E712
        )
        .order_by(GeneratedAsset.created_at.desc())
    )
    assets = result.scalars().all()

    return [
        {
            "id": str(asset.id),
            "title": asset.title,
            "topic": (asset.metadata_ or {}).get("topic", ""),
            "style": (asset.metadata_ or {}).get("style", "review"),
            "dialogue": (asset.content or {}).get("dialogue", []),
            "created_at": asset.created_at.isoformat() if asset.created_at else None,
        }
        for asset in assets
    ]
