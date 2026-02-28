"""Course CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.course import Course
from models.content import CourseContentTree
from models.user import User
from schemas.course import CourseCreate, CourseResponse, ContentNodeResponse
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()

DEFAULT_USER_NAME = "Local User"


def _serialize_content_tree(nodes: list[CourseContentTree]) -> list[ContentNodeResponse]:
    by_parent: dict[uuid.UUID | None, list[CourseContentTree]] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    for siblings in by_parent.values():
        siblings.sort(key=lambda item: (item.order_index, item.created_at))

    def build(node: CourseContentTree) -> ContentNodeResponse:
        return ContentNodeResponse(
            id=node.id,
            title=node.title,
            content=node.content,
            level=node.level,
            order_index=node.order_index,
            source_type=node.source_type,
            children=[build(child) for child in by_parent.get(node.id, [])],
        )

    return [build(node) for node in by_parent.get(None, [])]


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
async def list_courses(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Course).where(Course.user_id == user.id).order_by(Course.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=CourseResponse, status_code=201)
async def create_course(body: CourseCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    course = Course(user_id=user.id, name=body.name, description=body.description)
    db.add(course)
    await db.commit()
    await db.refresh(course)
    return course


@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_course_or_404(db, course_id, user_id=user.id)


@router.get("/{course_id}/content-tree", response_model=list[ContentNodeResponse])
async def get_content_tree(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get the full content tree for a course (top-level nodes with children)."""
    await get_course_or_404(db, course_id, user_id=user.id)
    result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id)
        .order_by(CourseContentTree.level, CourseContentTree.order_index, CourseContentTree.created_at)
    )
    return _serialize_content_tree(result.scalars().all())


@router.delete("/{course_id}", status_code=204)
async def delete_course(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    course = await get_course_or_404(db, course_id, user_id=user.id)
    await db.delete(course)
    await db.commit()
