"""AI Notes restructuring endpoint."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.content import CourseContentTree
from services.parser.notes import restructure_notes
from services.preference.engine import resolve_preferences
from routers.courses import get_or_create_user

router = APIRouter()


class RestructureRequest(BaseModel):
    content_node_id: uuid.UUID
    format_override: str | None = None  # Override user preference


class RestructureResponse(BaseModel):
    original_title: str
    ai_content: str
    format_used: str


@router.post("/restructure", response_model=RestructureResponse)
async def restructure_content(body: RestructureRequest, db: AsyncSession = Depends(get_db)):
    """Restructure a content node based on user preferences."""
    result = await db.execute(
        select(CourseContentTree).where(CourseContentTree.id == body.content_node_id)
    )
    node = result.scalar_one_or_none()
    if not node or not node.content:
        raise HTTPException(status_code=404, detail="Content node not found or empty")

    # Get user preferences
    user = await get_or_create_user(db)
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
