"""Progress tracking — core progress endpoints (CRUD, overview)."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.progress.summary import course_summary, overview

from routers.progress_analytics import router as analytics_router
from routers.progress_knowledge import router as knowledge_router

router = APIRouter()

# Include sub-routers so all endpoints remain under /api/progress
router.include_router(analytics_router)
router.include_router(knowledge_router)


# ── Progress Endpoints ──


@router.get("/courses/{course_id}", summary="Get course progress", description="Return learning progress overview for a specific course.")
async def get_course_progress(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get learning progress overview for a course."""
    await get_course_or_404(db, course_id, user_id=user.id)
    return await course_summary(db, user.id, course_id)


@router.get("/overview", summary="Get learning overview", description="Return aggregate cross-course learning analytics for the current user.")
async def get_learning_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate cross-course learning analytics for the current user."""
    return await overview(db, user.id)
