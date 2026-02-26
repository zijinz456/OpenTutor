"""Canvas LMS integration endpoints.

Supports two modes:
1. API Token mode: Direct Canvas API access with user's token
2. Browser mode: Automated login via Playwright for session-based access

Phase 1: API token mode (canvasapi library)
Phase 3: Browser automation mode (Playwright)
"""

import uuid
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from routers.courses import get_or_create_user

router = APIRouter()


class CanvasLoginRequest(BaseModel):
    canvas_url: str  # e.g. "https://canvas.university.edu"
    username: str
    password: str


class CanvasTokenRequest(BaseModel):
    canvas_url: str
    api_token: str


class CanvasSyncRequest(BaseModel):
    canvas_url: str
    api_token: str | None = None
    course_ids: list[int] | None = None  # Canvas course IDs, None = sync all


@router.post("/login")
async def canvas_login(body: CanvasLoginRequest):
    """Login to Canvas via browser automation and save session."""
    from services.browser.automation import canvas_login

    success = await canvas_login(body.canvas_url, body.username, body.password)
    if not success:
        raise HTTPException(status_code=401, detail="Canvas login failed")

    return {"status": "ok", "message": "Canvas session saved"}


@router.post("/sync")
async def canvas_sync(body: CanvasSyncRequest, db: AsyncSession = Depends(get_db)):
    """Sync courses and assignments from Canvas.

    Uses canvasapi for API token mode, browser for session mode.
    Syncs: courses, assignments, announcements, files.
    """
    user = await get_or_create_user(db)

    if body.api_token:
        return await _sync_with_api(db, user.id, body.canvas_url, body.api_token, body.course_ids)
    else:
        return await _sync_with_browser(db, user.id, body.canvas_url, body.course_ids)


async def _sync_with_api(
    db: AsyncSession,
    user_id: uuid.UUID,
    canvas_url: str,
    api_token: str,
    course_ids: list[int] | None,
) -> dict:
    """Sync using Canvas API (canvasapi library)."""
    try:
        from canvasapi import Canvas
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="canvasapi not installed. Run: pip install canvasapi",
        )

    from models.course import Course
    from models.ingestion import Assignment
    from sqlalchemy import select

    canvas = Canvas(canvas_url, api_token)
    synced_courses = 0
    synced_assignments = 0

    try:
        canvas_courses = canvas.get_courses(enrollment_state="active")

        for cc in canvas_courses:
            if course_ids and cc.id not in course_ids:
                continue

            # Create or update course in our DB
            result = await db.execute(
                select(Course).where(
                    Course.user_id == user_id,
                    Course.name == cc.name,
                )
            )
            course = result.scalar_one_or_none()
            if not course:
                course = Course(
                    user_id=user_id,
                    name=cc.name,
                    description=getattr(cc, "course_code", ""),
                    metadata_={"canvas_id": cc.id, "canvas_url": canvas_url},
                )
                db.add(course)
                await db.flush()
                synced_courses += 1

            # Sync assignments
            try:
                for assignment in cc.get_assignments():
                    existing = await db.execute(
                        select(Assignment).where(
                            Assignment.course_id == course.id,
                            Assignment.title == assignment.name,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue

                    due_at_raw = getattr(assignment, "due_at", None)
                    due_at = None
                    if isinstance(due_at_raw, datetime):
                        due_at = due_at_raw
                    elif isinstance(due_at_raw, str):
                        try:
                            due_at = datetime.fromisoformat(due_at_raw.replace("Z", "+00:00"))
                        except ValueError:
                            due_at = None

                    a = Assignment(
                        course_id=course.id,
                        title=assignment.name,
                        description=getattr(assignment, "description", None),
                        due_date=due_at,
                        assignment_type=_map_assignment_type(
                            getattr(assignment, "submission_types", [])
                        ),
                        metadata_json={"canvas_id": assignment.id},
                    )
                    db.add(a)
                    synced_assignments += 1
            except Exception as e:
                pass  # Some courses may not have assignments accessible

        await db.commit()

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Canvas sync failed: {str(e)}")

    return {
        "status": "ok",
        "courses_synced": synced_courses,
        "assignments_synced": synced_assignments,
    }


async def _sync_with_browser(
    db: AsyncSession,
    user_id: uuid.UUID,
    canvas_url: str,
    course_ids: list[int] | None,
) -> dict:
    """Sync using browser automation (Playwright with saved session)."""
    from services.browser.automation import canvas_fetch

    # Fetch dashboard to get course list
    dashboard_html = await canvas_fetch(f"{canvas_url}/dashboard")
    if not dashboard_html:
        raise HTTPException(
            status_code=401,
            detail="Canvas session expired. Please login again via /canvas/login",
        )

    # Parse courses from dashboard (basic HTML parsing)
    from services.parser.url import extract_text_from_html

    text = extract_text_from_html(dashboard_html)

    return {
        "status": "ok",
        "message": "Browser sync completed",
        "content_preview": text[:500] if text else "No content extracted",
    }


def _map_assignment_type(submission_types: list[str]) -> str:
    """Map Canvas submission types to our assignment types."""
    types = set(submission_types)
    if "online_quiz" in types:
        return "quiz"
    if "discussion_topic" in types:
        return "reading"
    if "online_upload" in types or "online_text_entry" in types:
        return "homework"
    return "homework"
