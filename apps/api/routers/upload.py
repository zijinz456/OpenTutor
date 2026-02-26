"""File upload, URL scraping, and ingestion pipeline endpoints.

Phase 0-A: Basic PDF upload + URL scrape → content tree.
Phase 1: Full 7-step ingestion pipeline with classification + multi-format.
"""

import asyncio
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db, async_session
from models.course import Course
from models.ingestion import IngestionJob
from models.user import User
from services.ingestion.pipeline import run_ingestion_pipeline
from services.auth.dependency import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


async def _background_embed(course_id: uuid.UUID):
    """Fire-and-forget: compute embeddings for newly ingested content."""
    try:
        from services.embedding.content import embed_course_content
        async with async_session() as db:
            await embed_course_content(db, course_id)
            await db.commit()
    except Exception as e:
        logger.debug(f"Background embedding failed: {e}")


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload any file → 7-step ingestion pipeline → content tree.

    Supports: PDF, PPTX, DOCX, HTML, TXT, MD.
    Phase 1: Added multi-format support + classification pipeline.
    """
    try:
        cid = uuid.UUID(course_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid course_id") from e

    result = await db.execute(select(Course).where(Course.id == cid))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    supported_exts = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".html", ".htm", ".txt", ".md"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in supported_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Supported: {', '.join(supported_exts)}",
        )

    file_bytes = await file.read()
    if len(file_bytes) > settings.max_upload_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large")

    # Save file to disk
    import hashlib
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    save_path = os.path.join(settings.upload_dir, f"{file_hash}_{file.filename}")
    with open(save_path, "wb") as f:
        f.write(file_bytes)

    # Run ingestion pipeline
    job = await run_ingestion_pipeline(
        db=db,
        user_id=user.id,
        file_path=save_path,
        filename=file.filename,
        course_id=cid,
        file_bytes=file_bytes,
    )
    await db.commit()

    if job.status == "failed":
        raise HTTPException(status_code=500, detail=job.error_message or "Ingestion failed")

    # Fire background embedding computation
    if (job.dispatched_to or {}).get("content_tree", 0) > 0:
        asyncio.create_task(_background_embed(cid))

    return {
        "status": "ok",
        "file": file.filename,
        "job_id": str(job.id),
        "category": job.content_category,
        "dispatched_to": job.dispatched_to,
        "nodes_created": (job.dispatched_to or {}).get("content_tree", 0),
        "course_id": str(cid),
    }


@router.post("/url")
async def scrape_url(
    url: str = Form(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Scrape a URL → ingestion pipeline → content tree."""
    try:
        cid = uuid.UUID(course_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid course_id") from e

    result = await db.execute(select(Course).where(Course.id == cid))
    course = result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")

    job = await run_ingestion_pipeline(
        db=db,
        user_id=user.id,
        url=url,
        filename=url.split("/")[-1] or "webpage",
        course_id=cid,
    )
    await db.commit()

    if job.status == "failed":
        raise HTTPException(status_code=500, detail=job.error_message or "Scrape failed")

    # Fire background embedding computation
    if (job.dispatched_to or {}).get("content_tree", 0) > 0:
        asyncio.create_task(_background_embed(cid))

    return {
        "status": "ok",
        "url": url,
        "job_id": str(job.id),
        "category": job.content_category,
        "nodes_created": (job.dispatched_to or {}).get("content_tree", 0),
        "course_id": str(cid),
    }


@router.get("/jobs/{course_id}")
async def list_ingestion_jobs(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """List ingestion jobs for a course."""
    result = await db.execute(
        select(IngestionJob)
        .where(IngestionJob.course_id == course_id)
        .order_by(IngestionJob.created_at.desc())
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(j.id),
            "filename": j.original_filename,
            "source_type": j.source_type,
            "category": j.content_category,
            "status": j.status,
            "dispatched_to": j.dispatched_to,
            "created_at": j.created_at.isoformat(),
        }
        for j in jobs
    ]
