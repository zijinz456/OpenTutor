"""Progress analytics endpoints — trends, weekly reports, templates, memory."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user
from services.progress.summary import daily_activity, weekly_report

router = APIRouter()


class ApplyTemplateRequest(BaseModel):
    template_id: uuid.UUID
    course_id: uuid.UUID | None = None


# ── Time-Series Analytics ──


@router.get("/trends", summary="Get global learning trends", description="Return daily learning trends aggregated across all courses.")
async def get_global_trends(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get global daily learning trends across all courses (from practice attempts)."""
    days = max(1, min(days, 365))
    return {"days": days, "trend": await daily_activity(db, user.id, days)}


# ── Weekly Report ──


@router.get("/weekly-report", summary="Get weekly report", description="Generate a weekly learning report comparing this week to last week.")
async def get_weekly_report(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a weekly learning report with this-week vs last-week comparison."""
    return await weekly_report(db, user.id)


# ── Memory Stats ──


@router.get("/memory-stats", summary="Get memory statistics", description="Return memory consolidation statistics for the current user.")
async def get_memory_stats_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get memory consolidation statistics."""
    from services.agent.memory_agent import get_memory_stats

    return await get_memory_stats(db, user.id)


@router.post("/memory-consolidate", summary="Trigger memory consolidation", description="Run memory consolidation pipeline for the current user.")
async def trigger_consolidation(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger memory consolidation for the user."""
    from services.memory.pipeline import consolidate_memory

    result = await consolidate_memory(db, user.id)
    await db.commit()
    return result


# ── Templates ──


@router.get("/templates", summary="List learning templates", description="Return all available learning templates.")
async def list_templates():
    """List all available learning templates."""
    from services.templates.system import list_templates

    return list_templates()


@router.post("/templates/apply", summary="Apply a learning template", description="Apply a learning template to the user's preferences.")
async def apply_template(
    body: ApplyTemplateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a learning template to the user's preferences."""
    from services.templates.system import apply_template

    result = await apply_template(db, user.id, body.template_id, body.course_id)
    await db.commit()
    return result
