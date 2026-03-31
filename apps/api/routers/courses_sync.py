"""Course sync endpoint: re-crawl and re-ingest changed content."""

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, async_session
from models.ingestion import IngestionJob
from models import scrape as models_scrape
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{course_id}/sync", summary="Sync course from source", description="Re-crawl the original source URL and ingest only new or changed content.")
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

    await get_course_or_404(db, course_id, user_id=user.id)

    # 1. Find the original scrape URL -- try ScrapeSource first, then IngestionJob
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
