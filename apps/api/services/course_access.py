"""Shared helpers for resolving course records consistently."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.course import Course


async def get_course_or_404(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> Course:
    """Return a course or raise 404.

    In local single-user mode we only require the course to exist.
    When auth is enabled, ownership is enforced if a user id is provided.
    """
    query = select(Course).where(Course.id == course_id)
    if settings.auth_enabled and user_id is not None:
        query = query.where(Course.user_id == user_id)

    result = await db.execute(query)
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course
