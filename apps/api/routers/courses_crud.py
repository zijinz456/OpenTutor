"""Course CRUD endpoints: list, create, get, update, delete, content tree."""

import logging
import uuid

from fastapi import APIRouter, Depends, Request
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
from schemas.course import CourseCreate, CourseOverviewCard, CourseResponse, ContentNodeResponse, CourseUpdate
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)

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
            content_category=getattr(node, "content_category", None),
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


@router.get("/", response_model=list[CourseResponse], summary="List all courses", description="Return all courses for the current user, ordered by creation date.")
async def list_courses(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Course).where(Course.user_id == user.id).order_by(Course.created_at.desc())
    )
    return result.scalars().all()


@router.get("/overview", response_model=list[CourseOverviewCard], summary="List course overview cards", description="Return enriched course cards with file counts, goals, and agent activity.")
async def list_course_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    file_counts = (
        select(
            IngestionJob.course_id.label("course_id"),
            func.count(IngestionJob.id).label("file_count"),
        )
        .where(IngestionJob.user_id == user.id)
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
        .where(StudyGoal.status == "active", StudyGoal.user_id == user.id)
        .group_by(StudyGoal.course_id)
        .subquery()
    )
    pending_tasks = (
        select(
            AgentTask.course_id.label("course_id"),
            func.count(AgentTask.id).label("pending_task_count"),
        )
        .where(AgentTask.status.in_(("queued", "running", "resuming", "cancel_requested")), AgentTask.user_id == user.id)
        .group_by(AgentTask.course_id)
        .subquery()
    )
    pending_approvals = (
        select(
            AgentTask.course_id.label("course_id"),
            func.count(AgentTask.id).label("pending_approval_count"),
        )
        .where(AgentTask.status.in_(("awaiting_approval", "pending_approval")), AgentTask.user_id == user.id)
        .group_by(AgentTask.course_id)
        .subquery()
    )
    last_activity = (
        select(
            AgentTask.course_id.label("course_id"),
            func.max(AgentTask.updated_at).label("last_agent_activity_at"),
        )
        .where(AgentTask.user_id == user.id)
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


@router.post("/", response_model=CourseResponse, status_code=201, summary="Create a course", description="Create a new course for the current user.")
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


@router.get("/{course_id}", response_model=CourseResponse, summary="Get a course", description="Return a single course by ID for the current user.")
async def get_course(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await get_course_or_404(db, course_id, user_id=user.id)


@router.patch("/{course_id}", response_model=CourseResponse, summary="Update a course", description="Partially update course name, description, or metadata.")
async def update_course(
    course_id: uuid.UUID,
    body: CourseUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await get_course_or_404(db, course_id, user_id=user.id)
    if body.name is not None:
        course.name = body.name
    if body.description is not None:
        course.description = body.description
    if body.metadata is not None:
        existing_metadata = dict(course.metadata_ or {})
        incoming_metadata = body.metadata.model_dump(exclude_none=True)
        existing_metadata.update(incoming_metadata)
        course.metadata_ = existing_metadata
    await db.commit()
    await db.refresh(course)
    return course


@router.get("/{course_id}/layout", summary="Get workspace layout", description="Return the saved workspace layout from course metadata.")
async def get_layout(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the saved workspace layout configuration from course metadata."""
    course = await get_course_or_404(db, course_id, user_id=user.id)
    metadata = course.metadata_ or {}
    return metadata.get("spaceLayout", {})


@router.patch("/{course_id}/layout", summary="Update workspace layout", description="Save the workspace layout configuration in course metadata.")
async def update_layout(
    course_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the workspace layout configuration stored in course metadata."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    course = await get_course_or_404(db, course_id, user_id=user.id)
    metadata = dict(course.metadata_ or {})
    metadata["spaceLayout"] = body
    mode = body.get("mode")
    if isinstance(mode, str) and mode:
        metadata["learning_mode"] = mode
    course.metadata_ = metadata
    await db.commit()
    await db.refresh(course)
    return {"status": "ok", "layout": body}


@router.get("/{course_id}/content-tree", response_model=list[ContentNodeResponse], summary="Get course content tree", description="Return the hierarchical content tree for a course.")
async def get_content_tree(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Get the full content tree for a course (top-level nodes with children)."""
    await get_course_or_404(db, course_id, user_id=user.id)
    result = await db.execute(
        select(CourseContentTree)
        .where(CourseContentTree.course_id == course_id)
        .order_by(CourseContentTree.level, CourseContentTree.order_index, CourseContentTree.created_at)
    )
    return _serialize_content_tree(result.scalars().all())


@router.get("/{course_id}/course-info", summary="Get course info summary", description="Return structured course info: grading scheme, assignments, deadlines, quiz details.")
async def get_course_info(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Extract and summarize information-type content (syllabus, assignments, quizzes)."""
    from models.ingestion import Assignment

    await get_course_or_404(db, course_id, user_id=user.id)

    # Get syllabus content nodes (assignments listing, quizzes, etc.)
    syllabus_result = await db.execute(
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.content_category == "syllabus",
            CourseContentTree.content.isnot(None),
        )
        .order_by(CourseContentTree.order_index)
    )
    syllabus_nodes = syllabus_result.scalars().all()

    # Get assignments from dedicated table
    assignments_result = await db.execute(
        select(Assignment)
        .where(Assignment.course_id == course_id)
        .order_by(Assignment.due_date.asc().nullslast())
    )
    assignments = assignments_result.scalars().all()

    # Build grading info from "Assignments" summary node
    grading_items = []
    for node in syllabus_nodes:
        if node.title == "Assignments" and node.content:
            import re
            # Parse lines like: "**Short Assignment 1** (due: 2026-03-22) [12.0 pts]"
            for match in re.finditer(
                r"\*\*(.+?)\*\*\s*\(due:\s*([^)]+)\)\s*\[([0-9.]+)\s*pts?\]",
                node.content,
            ):
                grading_items.append({
                    "title": match.group(1).strip(),
                    "due_date": match.group(2).strip(),
                    "points": float(match.group(3)),
                })
            break

    # Build quiz info
    quizzes = []
    for node in syllabus_nodes:
        if "quiz" in node.title.lower() and "reference" not in node.title.lower():
            quizzes.append({
                "title": node.title,
                "content": (node.content or "")[:500],
            })

    # Build assignment list from DB
    assignment_list = [
        {
            "title": a.title,
            "type": a.assignment_type,
            "due_date": str(a.due_date) if a.due_date else None,
            "description": (a.description or "")[:200],
        }
        for a in assignments
    ]

    return {
        "grading_scheme": grading_items,
        "quizzes": quizzes,
        "assignments": assignment_list,
        "syllabus_node_count": len(syllabus_nodes),
    }


@router.delete("/{course_id}", status_code=204, summary="Delete a course", description="Permanently delete a course and its associated data.")
async def delete_course(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    course = await get_course_or_404(db, course_id, user_id=user.id)
    await db.delete(course)
    await db.commit()
