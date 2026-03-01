"""File upload, URL scraping, and ingestion pipeline endpoints.

Phase 0-A: Basic PDF upload + URL scrape → content tree.
Phase 1: Full 7-step ingestion pipeline with classification + multi-format.
"""

import asyncio
import ipaddress
import logging
import mimetypes
import os
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from libs.exceptions import AppError, NotFoundError, PermissionDeniedError, ValidationError
from database import get_db, async_session
from models.ingestion import IngestionJob
from models.user import User
from services.ingestion.pipeline import _set_job_phase
from services.ingestion.pipeline import run_ingestion_pipeline
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

logger = logging.getLogger(__name__)


def _is_blocked_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local


def _validate_url(url: str) -> str:
    """Validate URL to prevent SSRF attacks."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("Only HTTP/HTTPS URLs are allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("Invalid URL")

    # Block internal/private IPs
    try:
        if _is_blocked_ip(hostname):
            raise ValidationError("Internal URLs are not allowed")
    except ValueError:
        # Not an IP — hostname, allow but check for obvious internal hostnames
        blocked_hosts = {
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "[::]",
            "[::1]",
            "metadata.google.internal",
        }
        if hostname.lower() in blocked_hosts:
            raise ValidationError("Internal URLs are not allowed")
        try:
            resolved = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            raise ValidationError("Hostname could not be resolved") from None
        for entry in resolved:
            resolved_ip = entry[4][0]
            if _is_blocked_ip(resolved_ip):
                raise ValidationError("Internal URLs are not allowed")

    return url


def _load_scrape_fixture_html(url: str) -> str | None:
    """Load deterministic HTML fixtures for local E2E scrape flows.

    This is only active when settings.scrape_fixture_dir is configured.
    URLs must use the reserved host opentutor-e2e.local.
    """
    if not settings.scrape_fixture_dir:
        return None

    parsed = urlparse(url)
    if parsed.hostname != "opentutor-e2e.local":
        return None

    slug = (parsed.path or "/").strip("/") or "index"
    safe_slug = re.sub(r"[^a-zA-Z0-9/_-]", "", slug)
    fixture_path = Path(settings.scrape_fixture_dir, f"{safe_slug}.html")
    if not fixture_path.exists():
        raise NotFoundError(f"Scrape fixture for {parsed.path or '/'}")
    return fixture_path.read_text(encoding="utf-8")


router = APIRouter()


async def _background_embed(course_id: uuid.UUID, job_id: uuid.UUID):
    """Fire-and-forget: compute embeddings for newly ingested content."""
    try:
        from services.embedding.content import embed_course_content
        async with async_session() as db:
            job = await db.get(IngestionJob, job_id)
            if job:
                _set_job_phase(
                    job,
                    status="embedding",
                    progress_percent=max(job.progress_percent or 0, 92),
                    embedding_status="running",
                    nodes_created=job.nodes_created,
                )
                await db.flush()
            await embed_course_content(db, course_id)
            if job:
                _set_job_phase(
                    job,
                    status="completed",
                    progress_percent=100,
                    embedding_status="completed",
                    nodes_created=job.nodes_created,
                )
            await db.commit()
    except Exception as e:
        try:
            async with async_session() as db:
                job = await db.get(IngestionJob, job_id)
                if job:
                    _set_job_phase(
                        job,
                        status="failed",
                        progress_percent=job.progress_percent or 90,
                        embedding_status="failed",
                        nodes_created=job.nodes_created,
                        error_message=str(e),
                    )
                    await db.commit()
        except Exception:
            logger.debug("Failed to persist embedding failure for job %s", job_id, exc_info=True)
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
        raise ValidationError("Invalid course_id") from e

    await get_course_or_404(db, cid, user_id=user.id)

    # Validate file
    if not file.filename:
        raise ValidationError("No filename provided")

    supported_exts = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".html", ".htm", ".txt", ".md"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in supported_exts:
        raise ValidationError(f"Unsupported file type: {ext}. Supported: {', '.join(supported_exts)}")

    file_bytes = await file.read()
    if len(file_bytes) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValidationError("File too large")

    # Save file to disk
    import hashlib
    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    os.makedirs(settings.upload_dir, exist_ok=True)
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
        raise AppError(job.error_message or "Ingestion failed")

    # Fire background embedding computation
    if (job.dispatched_to or {}).get("content_tree", 0) > 0:
        asyncio.create_task(_background_embed(cid, job.id))

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
    fixture_html = _load_scrape_fixture_html(url)
    if fixture_html is None:
        _validate_url(url)
    try:
        cid = uuid.UUID(course_id)
    except ValueError as e:
        raise ValidationError("Invalid course_id") from e

    await get_course_or_404(db, cid, user_id=user.id)

    job = await run_ingestion_pipeline(
        db=db,
        user_id=user.id,
        url=url,
        filename=url.split("/")[-1] or "webpage",
        course_id=cid,
        pre_fetched_html=fixture_html,
    )
    await db.commit()

    if job.status == "failed":
        raise AppError(job.error_message or "Scrape failed")

    # Fire background embedding computation
    if (job.dispatched_to or {}).get("content_tree", 0) > 0:
        asyncio.create_task(_background_embed(cid, job.id))

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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List ingestion jobs for a course."""
    await get_course_or_404(db, course_id, user_id=user.id)
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
            "phase_label": j.phase_label,
            "progress_percent": j.progress_percent,
            "embedding_status": j.embedding_status,
            "nodes_created": j.nodes_created,
            "error_message": j.error_message,
            "dispatched_to": j.dispatched_to,
            "created_at": j.created_at.isoformat(),
            "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        }
        for j in jobs
    ]


@router.get("/files/by-course/{course_id}")
async def list_course_files(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List uploaded files for a course."""
    result = await db.execute(
        select(IngestionJob)
        .where(
            IngestionJob.course_id == course_id,
            IngestionJob.status == "completed",
            IngestionJob.file_path.isnot(None),
        )
        .order_by(IngestionJob.created_at.desc())
    )
    jobs = result.scalars().all()
    return [
        {
            "id": str(job.id),
            "job_id": str(job.id),
            "filename": job.original_filename,
            "file_name": job.original_filename,
            "mime_type": job.mime_type,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }
        for job in jobs
    ]


@router.get("/files/{job_id}")
async def get_uploaded_file(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve an uploaded file for preview (e.g., PDF viewer)."""
    result = await db.execute(
        select(IngestionJob).where(IngestionJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job or not job.file_path:
        raise NotFoundError("File")

    file_path = Path(job.file_path).resolve()
    upload_dir = Path(settings.upload_dir).resolve()
    # Path traversal protection
    if not str(file_path).startswith(str(upload_dir)):
        raise PermissionDeniedError("Access denied")

    if not file_path.exists():
        raise NotFoundError("File on disk")

    # Determine media type from original filename
    media_type = mimetypes.guess_type(job.original_filename or "")[0] or "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=job.original_filename,
    )
