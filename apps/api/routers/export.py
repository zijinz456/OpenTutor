"""Export endpoints for user data portability.

Provides a downloadable SQLite file containing the user's learning data
(memories, preferences, progress, KV store, tool calls, chat messages).
"""

import os
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from database import get_db
from services.auth.dependency import get_current_user

router = APIRouter(prefix="/export", tags=["export"])


def _cleanup_file(filepath: str) -> None:
    """Remove the temporary export file after the response is sent."""
    try:
        os.unlink(filepath)
    except OSError:
        pass


@router.get("/session")
async def export_session(
    course_id: str | None = Query(None, description="Optional course ID to scope the export"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export user session data as a downloadable SQLite file.

    The exported file contains memories, preferences, progress records,
    agent KV store entries, tool call events, and chat message history.
    Optionally filter by course_id to export only data for a single course.
    """
    from services.export.session_export import export_session_state

    cid = uuid.UUID(course_id) if course_id else None
    filepath = await export_session_state(db, user.id, cid)

    filename = f"opentutor_export_{user.id}"
    if cid:
        filename += f"_course_{cid}"
    filename += ".sqlite"

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/x-sqlite3",
        background=BackgroundTask(_cleanup_file, str(filepath)),
    )
