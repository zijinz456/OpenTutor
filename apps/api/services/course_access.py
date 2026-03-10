"""Shared helpers for resolving database records consistently."""

import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.exceptions import NotFoundError
from models.course import Course

T = TypeVar("T")


async def get_or_404(
    db: AsyncSession,
    model: type[T],
    record_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    label: str | None = None,
) -> T:
    """Return a record by primary key or raise NotFoundError.

    When ``user_id`` is provided, also checks ownership via the model's
    ``user_id`` column (if it exists).
    """
    query = select(model).where(model.id == record_id)  # type: ignore[attr-defined]
    if user_id is not None and hasattr(model, "user_id"):
        query = query.where(model.user_id == user_id)  # type: ignore[attr-defined]

    result = await db.execute(query)
    obj = result.scalar_one_or_none()
    if not obj:
        raise NotFoundError(label or model.__name__, record_id)  # type: ignore[attr-defined]
    return obj


async def get_course_or_404(
    db: AsyncSession,
    course_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> Course:
    """Return a course or raise 404."""
    return await get_or_404(db, Course, course_id, user_id=user_id, label="Course")
