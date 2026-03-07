"""File upload, URL scraping, and ingestion pipeline endpoints.

Phase 0-A: Basic PDF upload + URL scrape → content tree.
Phase 1: Full 7-step ingestion pipeline with classification + multi-format.
"""

import asyncio
import hashlib
import logging
import mimetypes
import os
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, UploadFile, File, Form, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from libs.exceptions import AppError, NotFoundError, PermissionDeniedError, ValidationError
from libs.url_validation import validate_url, validate_url_dns
from database import get_db, async_session
from models.content import CourseContentTree
from models.ingestion import IngestionJob
from models.practice import PracticeProblem
from models import scrape as models_scrape
from models.user import User
from services.ingestion.pipeline import _set_job_phase
from services.ingestion.pipeline import run_ingestion_pipeline
from services.agent.background_runtime import track_background_task
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.llm.readiness import ensure_llm_ready

logger = logging.getLogger(__name__)


def _safe_filename(filename: str) -> str:
    """Sanitize user-provided filename to prevent path traversal."""
    base = os.path.basename(filename)
    cleaned = re.sub(r'[^\w.\-]', '_', base)
    return (cleaned or "unnamed")[:255]


# Backward-compatible aliases used by unit tests and older imports.
_validate_url = validate_url
_validate_url_dns = validate_url_dns


def _normalize_scrape_url(url: str) -> str:
    return url.strip()


def _candidate_scrape_fixture_dirs() -> list[Path]:
    candidates = []
    if settings.scrape_fixture_dir:
        candidates.append(Path(settings.scrape_fixture_dir).expanduser())
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "tests" / "e2e" / "fixtures" / "scrape"
        if candidate.exists():
            candidates.append(candidate)
            break
    candidates.append(Path("/fixtures/e2e/scrape"))

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(candidate)
    return unique_paths


def _load_scrape_fixture_html(url: str) -> str | None:
    """Load deterministic HTML fixtures for local E2E scrape flows."""
    normalized_url = _normalize_scrape_url(url)
    parsed = urlparse(normalized_url)
    if (parsed.hostname or "").lower() != "opentutor-e2e.local":
        return None

    slug = (parsed.path or "/").strip("/") or "index"
    safe_slug = re.sub(r"[^a-zA-Z0-9/_-]", "", slug)
    searched_dirs = []
    for fixture_dir in _candidate_scrape_fixture_dirs():
        searched_dirs.append(str(fixture_dir))
        fixture_path = fixture_dir / f"{safe_slug}.html"
        if fixture_path.exists():
            return fixture_path.read_text(encoding="utf-8")

    if any(Path(path).exists() for path in searched_dirs):
        raise NotFoundError(f"Scrape fixture for {parsed.path or '/'}")
    return None


router = APIRouter()


async def _background_auto_generate(course_id: uuid.UUID, user_id: uuid.UUID):
    """Fire-and-forget: auto-generate starter quiz + flashcards + notes after ingestion."""
    try:
        await ensure_llm_ready("Auto-generated starter study assets")
    except Exception as exc:
        logger.debug("Skipping starter asset generation for course %s: %s", course_id, exc)
        return

    try:
        from services.ingestion.pipeline import auto_prepare
        summary = await auto_prepare(async_session, course_id, user_id)
        logger.info("auto_prepare complete for course %s: %s", course_id, summary)
    except Exception:
        logger.exception("Auto-generate study assets failed (best-effort)")


async def _background_import_canvas_quizzes(
    course_id: uuid.UUID,
    quiz_questions: list[dict],
) -> int:
    """Import parsed Canvas quiz questions as PracticeProblem records."""
    try:
        from services.practice.annotation import build_practice_problem
        from sqlalchemy import func

        async with async_session() as db:
            max_order_result = await db.execute(
                select(func.max(PracticeProblem.order_index)).where(
                    PracticeProblem.course_id == course_id,
                    PracticeProblem.is_archived == False,
                )
            )
            start_order = (max_order_result.scalar() or 0) + 1

            batch_id = uuid.uuid4()
            created = 0
            for i, q in enumerate(quiz_questions):
                if not q.get("question"):
                    continue
                problem = build_practice_problem(
                    course_id=course_id,
                    content_node_id=None,
                    title=q.get("problem_metadata", {}).get("source_section", "Canvas Quiz"),
                    question=q,
                    order_index=start_order + i,
                    source="canvas_import",
                    source_batch_id=batch_id,
                )
                db.add(problem)
                created += 1
            await db.commit()
            logger.info("Imported %d Canvas quiz questions for course %s", created, course_id)
            return created
    except Exception:
        logger.exception("Canvas quiz import failed (best-effort)")
        return 0


async def _background_embed(course_id: uuid.UUID, job_id: uuid.UUID, user_id: uuid.UUID | None = None):
    """Fire-and-forget: compute embeddings + auto-generate assets in parallel."""

    async def _do_embed():
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

    async def _do_auto_generate():
        if not user_id:
            return
        await _background_auto_generate(course_id, user_id)

    # Run embedding and auto-generation in parallel for speed
    try:
        results = await asyncio.gather(
            _do_embed(), _do_auto_generate(), return_exceptions=True,
        )
        # Check if embedding failed
        if isinstance(results[0], Exception):
            raise results[0]
        if isinstance(results[1], Exception):
            logger.debug("Auto-generate failed (non-critical): %s", results[1])
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
            logger.exception("Failed to persist embedding failure for job %s", job_id)
        logger.exception("Background embedding failed for job %s", job_id)


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload any file → 7-step ingestion pipeline → content tree."""
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
    with open(save_path, "wb") as f:
        f.write(file_bytes)

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


def _derive_filename(url: str) -> str:
    """Derive a meaningful filename from a URL."""
    from services.scraper.canvas_detector import detect_canvas_url

    canvas_info = detect_canvas_url(url)
    if canvas_info.is_canvas:
        return canvas_info.friendly_name

    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if segments:
        return segments[-1]
    return parsed.hostname or "webpage"


async def _fetch_canvas_with_auth(
    url: str,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> str | None:
    """Attempt auth-aware fetch for Canvas URLs."""
    from services.scraper.canvas_detector import detect_canvas_url

    canvas_info = detect_canvas_url(url)
    if not canvas_info.is_canvas:
        return None

    result = await db.execute(
        select(models_scrape.AuthSession).where(
            models_scrape.AuthSession.user_id == user_id,
            models_scrape.AuthSession.domain == canvas_info.domain,
            models_scrape.AuthSession.is_valid == True,  # noqa: E712
        )
    )
    auth_session = result.scalar_one_or_none()

    if not auth_session:
        src_result = await db.execute(
            select(models_scrape.ScrapeSource).where(
                models_scrape.ScrapeSource.user_id == user_id,
                models_scrape.ScrapeSource.auth_domain == canvas_info.domain,
                models_scrape.ScrapeSource.requires_auth == True,  # noqa: E712
            )
        )
        scrape_source = src_result.scalar_one_or_none()
        if scrape_source and scrape_source.session_name:
            try:
                from services.browser.automation import cascade_fetch
                html = await cascade_fetch(
                    url, require_auth=True, session_name=scrape_source.session_name,
                )
                if html and len(html) > 200:
                    return html
            except Exception as e:
                logger.debug("Canvas auth fetch via ScrapeSource failed: %s", e)
        return None

    session_name = auth_session.session_name
    try:
        from services.browser.automation import cascade_fetch
        html = await cascade_fetch(url, require_auth=True, session_name=session_name)
        if html and len(html) > 200:
            return html
    except Exception as e:
        logger.debug("Canvas auth fetch via AuthSession failed: %s", e)

    return None


@router.post("/url")
async def scrape_url(
    request: Request,
    url: str = Form(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Scrape a URL → ingestion pipeline → content tree."""
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
        # Note: For Canvas, we skip _fetch_canvas_with_auth (Playwright HTML scrape)
        # and rely on Canvas REST API extraction in the pipeline (via session cookies).
        # The pipeline handles CanvasAuthExpiredError for expired sessions.

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
                f"Please login to {canvas_info.domain} first via Settings → Canvas Login, "
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
        from services.ingestion.pipeline import (
            ingest_canvas_files, link_pdfs_to_canvas_topics,
            auto_summarize_titles, auto_prepare,
        )

        async def _background_canvas_pipeline():
            """Chain: ingest files → link to topics → summarize titles → auto-prepare."""
            await ingest_canvas_files(
                db_factory=async_session,
                user_id=user.id,
                course_id=cid,
                file_urls=canvas_file_urls,
                session_name=scrape_session_name,
                canvas_domain=canvas_info.domain,
            )
            # Phase 2: Link PDFs to Canvas topic nodes
            await link_pdfs_to_canvas_topics(
                db_factory=async_session,
                course_id=cid,
                file_urls=canvas_file_urls,
            )
            # Phase 3: AI-summarize meaningless file titles
            await auto_summarize_titles(
                db_factory=async_session,
                course_id=cid,
            )
            # Phase 4: Auto-prepare notes + flashcards + quiz
            await auto_prepare(
                db_factory=async_session,
                course_id=cid,
                user_id=user.id,
            )

        track_background_task(asyncio.create_task(_background_canvas_pipeline()))
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


@router.post("/image")
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
    with open(save_path, "wb") as f:
        f.write(file_bytes)

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
    if not str(file_path).startswith(str(upload_dir)):
        raise PermissionDeniedError("Access denied")

    if not file_path.exists():
        raise NotFoundError("File on disk")

    media_type = mimetypes.guess_type(job.original_filename or "")[0] or "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=job.original_filename,
    )
