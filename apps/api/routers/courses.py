"""Course CRUD endpoints."""

import asyncio
import hashlib
import logging
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, async_session
from models.agent_task import AgentTask
from models.course import Course
from models.content import CourseContentTree
from models.chat_session import ChatSession
from models.ingestion import IngestionJob
from models import scrape as models_scrape
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


@router.patch("/{course_id}", response_model=CourseResponse)
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
        course.metadata_ = body.metadata.model_dump(exclude_none=True)
    await db.commit()
    await db.refresh(course)
    return course


@router.patch("/{course_id}/layout")
async def update_layout(
    course_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the workspace layout configuration stored in course metadata."""
    body = await request.json()
    course = await get_course_or_404(db, course_id, user_id=user.id)
    metadata = dict(course.metadata_ or {})
    metadata["layout"] = body
    course.metadata_ = metadata
    await db.commit()
    await db.refresh(course)
    return {"status": "ok", "layout": body}


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


@router.post("/{course_id}/sync")
async def sync_course(
    course_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Re-crawl the original source URL and process only new/changed files.

    Finds the most recent URL-based ingestion job or ScrapeSource for the
    course, re-fetches content, and only re-ingests files whose content hash
    has changed.
    """
    from services.ingestion.pipeline import run_ingestion_pipeline
    from services.agent.background_runtime import track_background_task

    course = await get_course_or_404(db, course_id, user_id=user.id)

    # 1. Find the original scrape URL — try ScrapeSource first, then IngestionJob
    source_url: str | None = None
    session_name: str | None = None
    is_canvas = False

    # Check ScrapeSource records
    src_result = await db.execute(
        select(models_scrape.ScrapeSource)
        .where(
            models_scrape.ScrapeSource.course_id == course_id,
            models_scrape.ScrapeSource.user_id == user.id,
            models_scrape.ScrapeSource.enabled == True,  # noqa: E712
        )
        .order_by(models_scrape.ScrapeSource.updated_at.desc())
        .limit(1)
    )
    scrape_source = src_result.scalar_one_or_none()

    if scrape_source:
        source_url = scrape_source.url
        session_name = scrape_source.session_name
        is_canvas = scrape_source.source_type == "canvas"
    else:
        # Fall back to the most recent URL-based ingestion job
        job_result = await db.execute(
            select(IngestionJob)
            .where(
                IngestionJob.course_id == course_id,
                IngestionJob.user_id == user.id,
                IngestionJob.url.isnot(None),
                IngestionJob.source_type == "url",
            )
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
        last_url_job = job_result.scalar_one_or_none()
        if last_url_job:
            source_url = last_url_job.url

    if not source_url:
        from libs.exceptions import ValidationError
        raise ValidationError(
            "No source URL found for this course. "
            "Upload a URL first before syncing."
        )

    # 2. Gather existing content hashes for this course
    existing_result = await db.execute(
        select(IngestionJob.content_hash, IngestionJob.url, IngestionJob.original_filename)
        .where(
            IngestionJob.course_id == course_id,
            IngestionJob.content_hash.isnot(None),
            IngestionJob.status.in_(("completed", "embedding")),
        )
    )
    existing_hashes = {row.content_hash for row in existing_result.all()}

    # 3. Resolve Canvas auth if needed
    pre_fetched_html: str | None = None
    if not session_name:
        from services.scraper.canvas_detector import detect_canvas_url
        canvas_info = detect_canvas_url(source_url)
        if canvas_info.is_canvas:
            is_canvas = True
            from routers.scrape import _default_session_name
            session_name = _default_session_name(user.id, canvas_info.domain)

    if is_canvas and session_name:
        from routers.upload import _fetch_canvas_with_auth
        auth_html = await _fetch_canvas_with_auth(source_url, user.id, db)
        if auth_html:
            pre_fetched_html = auth_html

    # 4. Re-run ingestion pipeline (it will extract content and compute hashes)
    from routers.upload import _derive_filename
    filename = _derive_filename(source_url)

    job = await run_ingestion_pipeline(
        db=db,
        user_id=user.id,
        url=source_url,
        filename=f"sync_{filename}",
        course_id=course_id,
        pre_fetched_html=pre_fetched_html,
        session_name=session_name,
    )
    await db.commit()

    # 5. Compare hashes to determine what's new vs unchanged
    new_hash = job.content_hash
    is_new_content = new_hash is not None and new_hash not in existing_hashes
    new_files = 1 if is_new_content and job.status == "completed" else 0
    unchanged_files = 0 if is_new_content else 1
    updated_files = 0  # We treat changed content as new files in current model

    # 6. Kick off background embedding if new content was found
    is_test_request = request is not None and hasattr(request.app.state, "test_session_factory")
    if (job.nodes_created or 0) > 0 and is_new_content and not is_test_request:
        from routers.upload import _background_embed
        track_background_task(
            asyncio.create_task(_background_embed(course_id, job.id, user_id=user.id))
        )

    # 7. Handle Canvas file discovery for background ingestion
    canvas_file_urls = getattr(job, "_canvas_file_urls", [])
    files_discovered = len(canvas_file_urls)
    if canvas_file_urls and is_canvas and session_name and not is_test_request:
        from services.scraper.canvas_detector import detect_canvas_url
        canvas_info = detect_canvas_url(source_url)
        from services.ingestion.pipeline import (
            ingest_canvas_files, link_pdfs_to_canvas_topics,
            auto_summarize_titles, auto_prepare,
        )

        async def _background_canvas_sync():
            await ingest_canvas_files(
                db_factory=async_session,
                user_id=user.id,
                course_id=course_id,
                file_urls=canvas_file_urls,
                session_name=session_name,
                canvas_domain=canvas_info.domain,
            )
            await link_pdfs_to_canvas_topics(
                db_factory=async_session,
                course_id=course_id,
                file_urls=canvas_file_urls,
            )
            await auto_summarize_titles(
                db_factory=async_session,
                course_id=course_id,
            )
            await auto_prepare(
                db_factory=async_session,
                course_id=course_id,
                user_id=user.id,
            )

        track_background_task(asyncio.create_task(_background_canvas_sync()))

    # Update ScrapeSource if it exists
    if scrape_source:
        from datetime import datetime, timezone
        scrape_source.last_scraped_at = datetime.now(timezone.utc)
        scrape_source.last_content_hash = new_hash
        scrape_source.last_status = "success" if job.status != "failed" else "failed"
        scrape_source.last_ingestion_id = job.id
        if job.status == "failed":
            scrape_source.consecutive_failures += 1
            scrape_source.last_error = job.error_message
        else:
            scrape_source.consecutive_failures = 0
            scrape_source.last_error = None
        await db.commit()

    return {
        "status": "ok",
        "new_files": new_files,
        "updated_files": updated_files,
        "unchanged_files": unchanged_files,
        "files_discovered": files_discovered,
        "job_id": str(job.id),
        "job_status": job.status,
        "nodes_created": job.nodes_created or 0,
        "content_changed": is_new_content,
    }
