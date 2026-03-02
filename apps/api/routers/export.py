"""Export endpoints for user data portability.

Provides downloadable exports: SQLite session data, Anki flashcard decks,
and iCal study plan calendar files.
"""

import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from database import get_db
from services.auth.dependency import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/export", tags=["export"])


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    """Parse a UUID string, raising HTTPException 400 on invalid format."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {value!r}")


def _cleanup_file(filepath: str) -> None:
    """Remove the temporary export file after the response is sent."""
    try:
        os.unlink(filepath)
    except OSError:
        logger.warning("Failed to cleanup export temp file: %s", filepath)


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

    cid = _parse_uuid(course_id, "course_id") if course_id else None
    filepath = await export_session_state(db, user.id, cid)

    filename = f"opentutor_export_{user.id}"
    if cid:
        filename += f"_course_{cid}"
    filename += ".sqlite"

    logger.info("Session export for user %s (course=%s)", user.id, cid)
    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/x-sqlite3",
        background=BackgroundTask(_cleanup_file, str(filepath)),
    )


@router.get("/anki")
async def export_anki(
    course_id: str = Query(..., description="Course ID to export flashcards for"),
    batch_id: str | None = Query(None, description="Optional batch ID to export a specific set"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export flashcards as an Anki .apkg deck file.

    Downloads all non-archived flashcards for the specified course as an
    importable Anki deck. Optionally filter by batch_id for a specific set.
    """
    from services.export.anki_export import export_flashcards_to_anki

    cid = _parse_uuid(course_id, "course_id")
    bid = _parse_uuid(batch_id, "batch_id") if batch_id else None

    try:
        filepath = await export_flashcards_to_anki(db, user.id, cid, batch_id=bid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    logger.info("Anki export for user %s course %s (%d bytes)", user.id, cid, filepath.stat().st_size)
    return FileResponse(
        path=str(filepath),
        filename=f"opentutor_flashcards_{course_id}.apkg",
        media_type="application/octet-stream",
        background=BackgroundTask(_cleanup_file, str(filepath)),
    )


@router.get("/calendar")
async def export_calendar(
    course_id: str = Query(..., description="Course ID to export study plan for"),
    plan_batch_id: str | None = Query(None, description="Optional batch ID for a specific plan"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Export a study plan as an iCal (.ics) calendar file.

    Downloads the most recent study plan for the specified course as an
    iCal file importable into Google Calendar, Apple Calendar, Outlook, etc.
    """
    from services.export.calendar_export import export_study_plan_to_ical

    cid = _parse_uuid(course_id, "course_id")
    pid = _parse_uuid(plan_batch_id, "plan_batch_id") if plan_batch_id else None

    try:
        filepath = await export_study_plan_to_ical(db, user.id, cid, plan_batch_id=pid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    logger.info("Calendar export for user %s course %s", user.id, cid)
    return FileResponse(
        path=str(filepath),
        filename=f"opentutor_study_plan_{course_id}.ics",
        media_type="text/calendar",
        background=BackgroundTask(_cleanup_file, str(filepath)),
    )
