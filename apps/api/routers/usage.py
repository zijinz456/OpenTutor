"""Usage tracking API — LLM cost and token consumption endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.auth.dependency import get_current_user
from services.llm.usage import get_usage_summary

router = APIRouter(prefix="/api/usage", tags=["usage"])


@router.get("/summary")
async def usage_summary(
    period: str = Query("day", pattern="^(day|week|month)$"),
    course_id: str | None = None,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get aggregate usage summary (cost, tokens, calls) for a time period."""
    import uuid as _uuid

    cid = _uuid.UUID(course_id) if course_id else None
    return await get_usage_summary(db, user.id, period=period, course_id=cid)
