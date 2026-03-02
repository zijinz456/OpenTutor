"""Course CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.agent_task import AgentTask
from models.course import Course
from models.content import CourseContentTree
from models.chat_session import ChatSession
from models.ingestion import IngestionJob
from models.study_goal import StudyGoal
from models.user import User
from schemas.course import CourseCreate, CourseOverviewCard, CourseResponse, ContentNodeResponse
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


@router.get("/overview", response_model=list[CourseOverviewCard])
async def list_course_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_counts = (
        select(
            IngestionJob.course_id.label("course_id"),
            func.count(IngestionJob.id).label("file_count"),
        )
        .group_by(IngestionJob.course_id)
        .subquery()
    )
    content_counts = (
        select(
            CourseContentTree.course_id.label("course_id"),
            func.count(CourseContentTree.id).label("content_node_count"),
        )
        .group_by(CourseContentTree.course_id)
        .subquery()
    )
    goal_counts = (
        select(
            StudyGoal.course_id.label("course_id"),
            func.count(StudyGoal.id).label("active_goal_count"),
        )
        .where(StudyGoal.status == "active")
        .group_by(StudyGoal.course_id)
        .subquery()
    )
    pending_tasks = (
        select(
            AgentTask.course_id.label("course_id"),
            func.count(AgentTask.id).label("pending_task_count"),
        )
        .where(AgentTask.status.in_(("queued", "running", "resuming", "cancel_requested")))
        .group_by(AgentTask.course_id)
        .subquery()
    )
    pending_approvals = (
        select(
            AgentTask.course_id.label("course_id"),
            func.count(AgentTask.id).label("pending_approval_count"),
        )
        .where(AgentTask.status.in_(("awaiting_approval", "pending_approval")))
        .group_by(AgentTask.course_id)
        .subquery()
    )
    last_activity = (
        select(
            AgentTask.course_id.label("course_id"),
            func.max(AgentTask.updated_at).label("last_agent_activity_at"),
        )
        .group_by(AgentTask.course_id)
        .subquery()
    )
    latest_scene_id = (
        select(ChatSession.scene_id)
        .where(ChatSession.course_id == Course.id)
        .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    result = await db.execute(
        select(
            Course.id,
            Course.name,
            Course.description,
            Course.metadata_.label("metadata"),
            Course.created_at,
            Course.updated_at,
            func.coalesce(file_counts.c.file_count, literal(0)).label("file_count"),
            func.coalesce(content_counts.c.content_node_count, literal(0)).label("content_node_count"),
            func.coalesce(goal_counts.c.active_goal_count, literal(0)).label("active_goal_count"),
            func.coalesce(pending_tasks.c.pending_task_count, literal(0)).label("pending_task_count"),
            func.coalesce(pending_approvals.c.pending_approval_count, literal(0)).label("pending_approval_count"),
            last_activity.c.last_agent_activity_at,
            func.coalesce(latest_scene_id, Course.active_scene).label("last_scene_id"),
        )
        .select_from(Course)
        .outerjoin(file_counts, file_counts.c.course_id == Course.id)
        .outerjoin(content_counts, content_counts.c.course_id == Course.id)
        .outerjoin(goal_counts, goal_counts.c.course_id == Course.id)
        .outerjoin(pending_tasks, pending_tasks.c.course_id == Course.id)
        .outerjoin(pending_approvals, pending_approvals.c.course_id == Course.id)
        .outerjoin(last_activity, last_activity.c.course_id == Course.id)
        .where(Course.user_id == user.id)
        .order_by(Course.updated_at.desc(), Course.created_at.desc())
    )

    return [
        CourseOverviewCard(
            id=row.id,
            name=row.name,
            description=row.description,
            metadata=row.metadata,
            created_at=row.created_at,
            updated_at=row.updated_at,
            file_count=int(row.file_count or 0),
            content_node_count=int(row.content_node_count or 0),
            active_goal_count=int(row.active_goal_count or 0),
            pending_task_count=int(row.pending_task_count or 0),
            pending_approval_count=int(row.pending_approval_count or 0),
            last_agent_activity_at=row.last_agent_activity_at,
            last_scene_id=row.last_scene_id,
        )
        for row in result.all()
    ]


@router.post("/", response_model=CourseResponse, status_code=201)
async def create_course(body: CourseCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    course = Course(
        user_id=user.id,
        name=body.name,
        description=body.description,
        metadata_=body.metadata.model_dump(exclude_none=True) if body.metadata else None,
    )
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
