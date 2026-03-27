"""File upload, URL scraping, and ingestion pipeline endpoints."""

import asyncio
import hashlib
import logging
import mimetypes
import os
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from libs.exceptions import AppError, PermissionDeniedError, ValidationError, NotFoundError
from database import get_db, async_session
from models.ingestion import IngestionJob
from models.user import User
from services.ingestion.pipeline import run_ingestion_pipeline
from services.agent.background_runtime import track_background_task
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

import socket  # noqa: F401 — re-exported for test monkeypatching compatibility

from routers.upload_processing import (  # noqa: F401 — re-exported for consumers
    _safe_filename,
    _validate_url,
    _validate_url_dns,
    _normalize_scrape_url,
    _load_scrape_fixture_html,
    _derive_filename,
    _fetch_canvas_with_auth,
    _background_auto_generate,
    _background_import_canvas_quizzes,
    _background_embed,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/upload", summary="Upload a file", description="Upload a document and run the 7-step ingestion pipeline.")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload any file -> 7-step ingestion pipeline -> content tree."""
    try:
        cid = uuid.UUID(course_id)
    except ValueError as e:
        raise ValidationError("Invalid course_id") from e

    await get_course_or_404(db, cid, user_id=user.id)

    if not file.filename:
        raise ValidationError("No filename provided")

    supported_exts = {".pdf", ".pptx", ".ppt", ".docx", ".doc", ".html", ".htm", ".txt", ".md"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in supported_exts:
        raise ValidationError(f"Unsupported file type: {ext}. Supported: {', '.join(supported_exts)}")

    file_bytes = await file.read()
    if len(file_bytes) > settings.max_upload_size_mb * 1024 * 1024:
        raise ValidationError("File too large")

    # Validate magic bytes match declared extension for binary formats
    import filetype as ft
    detected = ft.guess(file_bytes)
    _MAGIC_EXT_MAP = {
        "application/pdf": {".pdf"},
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": {".pptx"},
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {".docx"},
        "application/zip": {".pptx", ".docx"},  # Office files are ZIP-based
    }
    if detected and detected.mime in _MAGIC_EXT_MAP:
        allowed_exts = _MAGIC_EXT_MAP[detected.mime]
        if ext not in allowed_exts:
            logger.warning(
                "SECURITY | MIME_MISMATCH | declared_ext=%s | detected_mime=%s | filename=%s",
                ext, detected.mime, file.filename,
            )
            raise ValidationError(
                f"File content ({detected.mime}) does not match extension ({ext})"
            )

    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", os.path.basename(file.filename)) or "unnamed"
    safe_name = safe_name[:255]
    save_path = os.path.join(settings.upload_dir, f"{file_hash}_{safe_name}")
    await asyncio.to_thread(Path(save_path).write_bytes, file_bytes)

    try:
        job = await run_ingestion_pipeline(
            db=db,
            user_id=user.id,
            file_path=save_path,
            filename=file.filename,
            course_id=cid,
            file_bytes=file_bytes,
        )
        await db.commit()
    except Exception:
        # Clean up saved file if ingestion fails, then re-raise the original error.
        try:
            os.remove(save_path)
        except OSError:
            logger.warning("Failed to clean up uploaded file: %s", save_path)
        raise

    if job.status == "failed":
        # Clean up on logical failure too
        try:
            os.remove(save_path)
        except OSError:
            pass
        raise AppError(job.error_message or "Ingestion failed")

    is_test_request = request is not None and hasattr(request.app.state, "test_session_factory")
    if (job.nodes_created or 0) > 0 and not is_test_request:
        track_background_task(asyncio.create_task(_background_embed(cid, job.id, user_id=user.id)))

    return {
        "status": "ok",
        "file": file.filename,
        "job_id": str(job.id),
        "category": job.content_category,
        "dispatched_to": job.dispatched_to,
        "nodes_created": job.nodes_created or 0,
        "course_id": str(cid),
    }


@router.post("/url", summary="Scrape a URL", description="Fetch content from a URL and run it through the ingestion pipeline.")
async def scrape_url(
    request: Request,
    url: str = Form(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Scrape a URL -> ingestion pipeline -> content tree."""
    from libs.url_validation import validate_url, validate_url_dns

    url = _normalize_scrape_url(url)
    fixture_html = _load_scrape_fixture_html(url)
    if fixture_html is not None:
        logger.info("Using local scrape fixture for %s", url)
    if fixture_html is None:
        validate_url(url)
        await validate_url_dns(url)
    try:
        cid = uuid.UUID(course_id)
    except ValueError as e:
        raise ValidationError("Invalid course_id") from e

    await get_course_or_404(db, cid, user_id=user.id)

    from services.scraper.canvas_detector import detect_canvas_url

    canvas_info = detect_canvas_url(url)
    pre_fetched = fixture_html
    requires_auth = False

    if canvas_info.is_canvas and fixture_html is None:
        requires_auth = True
        logger.info("Canvas URL detected: %s (course_id=%s, page=%s)",
                     canvas_info.domain, canvas_info.course_id, canvas_info.page_type)

    filename = _derive_filename(url)

    # Pass session_name for authenticated Canvas API access
    from routers.scrape import _default_session_name as _dsn
    scrape_session_name = None
    if canvas_info.is_canvas:
        scrape_session_name = _dsn(user.id, canvas_info.domain)

    job = await run_ingestion_pipeline(
        db=db,
        user_id=user.id,
        url=url,
        filename=filename,
        course_id=cid,
        pre_fetched_html=pre_fetched,
        session_name=scrape_session_name,
    )
    await db.commit()

    if job.status == "failed":
        error_msg = job.error_message or "Scrape failed"
        if requires_auth and not pre_fetched:
            error_msg = (
                f"Canvas URL requires authentication. "
                f"Please login to {canvas_info.domain} first via Settings -> Canvas Login, "
                f"then retry. Original error: {error_msg}"
            )
        raise AppError(error_msg)

    is_test_request = request is not None and hasattr(request.app.state, "test_session_factory")
    if (job.nodes_created or 0) > 0 and not is_test_request:
        track_background_task(asyncio.create_task(_background_embed(cid, job.id, user_id=user.id)))

    # Auto-ingest discovered Canvas files (PDFs, docs) in background,
    # then link PDFs to topics, summarize titles, and auto-generate notes.
    canvas_file_urls = getattr(job, "_canvas_file_urls", [])
    files_discovered = len(canvas_file_urls)
    if canvas_file_urls and canvas_info.is_canvas and scrape_session_name and not is_test_request:
        from routers.upload_processing import start_background_canvas_pipeline
        start_background_canvas_pipeline(
            user_id=user.id, course_id=cid,
            canvas_file_urls=canvas_file_urls,
            scrape_session_name=scrape_session_name,
            canvas_domain=canvas_info.domain,
        )
        logger.info("Queued %d Canvas files for background ingestion + auto-processing", files_discovered)

    # Auto-import Canvas quiz questions as PracticeProblem records
    canvas_quiz_questions = getattr(job, "_canvas_quiz_questions", [])
    if canvas_quiz_questions and not is_test_request:
        track_background_task(asyncio.create_task(
            _background_import_canvas_quizzes(
                course_id=cid,
                quiz_questions=canvas_quiz_questions,
            )
        ))
        logger.info("Queued %d Canvas quiz questions for import", len(canvas_quiz_questions))

    return {
        "status": "ok",
        "url": url,
        "job_id": str(job.id),
        "category": job.content_category,
        "nodes_created": job.nodes_created or 0,
        "course_id": str(cid),
        "is_canvas": canvas_info.is_canvas,
        "canvas_auth_used": requires_auth and pre_fetched is not None,
        "files_discovered": files_discovered,
        "quiz_questions_queued": len(canvas_quiz_questions),
    }


@router.get("/jobs/{course_id}", summary="List ingestion jobs", description="Return all ingestion jobs for a course with status and progress.")
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


@router.get("/files/by-course/{course_id}", summary="List course files", description="Return uploaded files for a course that completed ingestion.")
async def list_course_files(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List uploaded files for a course."""
    await get_course_or_404(db, course_id, user_id=user.id)

    result = await db.execute(
        select(IngestionJob)
        .where(
            IngestionJob.course_id == course_id,
            IngestionJob.user_id == user.id,
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


@router.post("/image", summary="Upload an image", description="Upload an image for chat context such as a math problem photo.")
async def upload_image(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload an image for chat context (e.g., math problem photo)."""
    import base64

    try:
        cid = uuid.UUID(course_id)
    except ValueError as e:
        raise ValidationError("Invalid course_id") from e

    await get_course_or_404(db, cid, user_id=user.id)

    if not file.filename:
        raise ValidationError("No filename provided")

    supported_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = file.content_type or ""
    if content_type not in supported_types:
        ext = os.path.splitext(file.filename)[1].lower()
        ext_to_mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
        content_type = ext_to_mime.get(ext, "")
        if content_type not in supported_types:
            raise ValidationError("Unsupported image type. Supported: JPEG, PNG, WebP, GIF")

    file_bytes = await file.read()
    max_image_size = 10 * 1024 * 1024  # 10MB
    if len(file_bytes) > max_image_size:
        raise ValidationError("Image too large (max 10MB)")

    file_hash = hashlib.sha256(file_bytes).hexdigest()[:16]
    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]", "_", os.path.basename(file.filename)) or "unnamed"
    safe_name = safe_name[:255]
    save_path = os.path.join(settings.upload_dir, f"img_{file_hash}_{safe_name}")
    await asyncio.to_thread(Path(save_path).write_bytes, file_bytes)

    b64_data = base64.b64encode(file_bytes).decode("utf-8")

    return {
        "status": "ok",
        "filename": file.filename,
        "content_type": content_type,
        "size_bytes": len(file_bytes),
        "base64": b64_data,
        "media_type": content_type,
        "course_id": str(cid),
    }


@router.get("/files/{job_id}", summary="Download an uploaded file", description="Serve an uploaded file by ingestion job ID for preview.")
async def get_uploaded_file(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve an uploaded file for preview (e.g., PDF viewer)."""
    result = await db.execute(
        select(IngestionJob).where(
            IngestionJob.id == job_id,
            IngestionJob.user_id == user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job or not job.file_path:
        raise NotFoundError("File")

    file_path = Path(job.file_path).resolve()
    upload_dir = Path(settings.upload_dir).resolve()
    if not file_path.is_relative_to(upload_dir):
        raise PermissionDeniedError("Access denied")

    if not file_path.exists():
        raise NotFoundError("File on disk")

    media_type = mimetypes.guess_type(job.original_filename or "")[0] or "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=job.original_filename,
    )
