"""AI Notes restructuring endpoint."""

import uuid

from fastapi import APIRouter, Depends
from libs.exceptions import NotFoundError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.content import CourseContentTree
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.parser.notes import restructure_notes
from services.preference.engine import resolve_preferences

router = APIRouter()


class RestructureRequest(BaseModel):
    content_node_id: uuid.UUID
    format_override: str | None = None  # Override user preference


class RestructureResponse(BaseModel):
    original_title: str
    ai_content: str
    format_used: str


class SaveGeneratedNotesRequest(BaseModel):
    course_id: uuid.UUID
    title: str
    markdown: str
    source_node_id: uuid.UUID | None = None
    replace_batch_id: uuid.UUID | None = None


@router.post("/restructure", response_model=RestructureResponse)
async def restructure_content(body: RestructureRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Restructure a content node based on user preferences."""
    result = await db.execute(
        select(CourseContentTree).where(CourseContentTree.id == body.content_node_id)
    )
    node = result.scalar_one_or_none()
    if not node or not node.content:
        raise NotFoundError(resource="content_node", resource_id=str(body.content_node_id))

    # Verify course ownership
    await get_course_or_404(db, node.course_id, user_id=user.id)

    # Get user preferences
    resolved = await resolve_preferences(db, user.id, node.course_id)

    note_format = body.format_override or resolved.preferences.get("note_format", "bullet_point")
    visual_pref = resolved.preferences.get("visual_preference", "auto")

    ai_content = await restructure_notes(
        node.content, node.title, note_format, visual_pref
    )

    return RestructureResponse(
        original_title=node.title,
        ai_content=ai_content,
        format_used=note_format,
    )


@router.post("/generated/save")
async def save_generated_notes(
    body: SaveGeneratedNotesRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, body.course_id, user_id=user.id)

    from services.generated_assets import save_generated_asset

    try:
        result = await save_generated_asset(
            db,
            user_id=user.id,
            course_id=body.course_id,
            asset_type="notes",
            title=body.title,
            content={"markdown": body.markdown},
            metadata={"source_node_id": str(body.source_node_id) if body.source_node_id else None},
            replace_batch_id=body.replace_batch_id,
        )
    except ValueError as exc:
        raise NotFoundError(resource="generated_asset", resource_id=str(body.replace_batch_id)) from exc

    await db.commit()
    return result


@router.get("/generated/{course_id}")
async def list_generated_notes(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, course_id, user_id=user.id)

    from services.generated_assets import list_generated_asset_batches

    return await list_generated_asset_batches(
        db,
        user_id=user.id,
        course_id=course_id,
        asset_type="notes",
    )
