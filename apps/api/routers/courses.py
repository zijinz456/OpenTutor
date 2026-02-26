"""Course CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models.course import Course
from models.content import CourseContentTree
from models.user import User
from schemas.course import CourseCreate, CourseResponse, ContentNodeResponse

router = APIRouter()

DEFAULT_USER_NAME = "Local User"


async def get_or_create_user(db: AsyncSession) -> User:
    """Get or create the single local user."""
    result = await db.execute(select(User).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        user = User(name=DEFAULT_USER_NAME)
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user


@router.get("/", response_model=list[CourseResponse])
async def list_courses(db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db)
    result = await db.execute(
        select(Course).where(Course.user_id == user.id).order_by(Course.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=CourseResponse, status_code=201)
async def create_course(body: CourseCreate, db: AsyncSession = Depends(get_db)):
    user = await get_or_create_user(db)
    course = Course(user_id=user.id, name=body.name, description=body.description)
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get("/{course_id}/content-tree", response_model=list[ContentNodeResponse])
async def get_content_tree(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Get the full content tree for a course (top-level nodes with children)."""
    result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id, CourseContentTree.parent_id.is_(None))
        .options(selectinload(CourseContentTree.children))
        .order_by(CourseContentTree.order_index)
    )
    return result.scalars().all()


@router.delete("/{course_id}", status_code=204)
async def delete_course(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    await db.delete(course)
    await db.commit()
