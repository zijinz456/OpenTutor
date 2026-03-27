"""Unified classification pipeline — 7-step ingestion.

Step 0: Preprocessing (xxhash dedup, expanded filename regex, content heuristics)
Step 1: MIME detection (filetype → python-magic → extension)
Step 2: Content extraction (Crawl4AI → loader_dict → legacy fallbacks)
Step 3: 3-tier classification (filename regex → content heuristics → LLM)
Step 4: Course fuzzy matching (thefuzz)
Step 5: Store to ingestion_jobs table
Step 6: Dispatch to business tables (content_tree, assignments)

References:
- Crawl4AI: unified content extraction (web + PDF + HTML)
- GPT-Researcher: loader_dict for Office formats, clean_soup for HTML
- Deep-Research: token-aware content trimming (trimPrompt pattern)
- PageIndex: code-block-aware tree building, tree thinning
- Marker: filetype MIME detection pattern
- Crawl4AI: xxhash for fast content dedup
"""

import hashlib
import logging
import uuid
from collections.abc import Mapping

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import IngestionJob
from libs.exceptions import IngestionError, reraise_as_app_error  # noqa: F401

# ── Backward-compatible re-exports ──
# All public names that external code imports from this module.
from services.ingestion.classification import (  # noqa: F401
    FILENAME_PATTERNS,
    CONTENT_HEURISTICS,
    classify_by_filename,
    classify_by_content_heuristics,
    detect_mime_type,
    extract_content_with_title,
    extract_content,
    CLASSIFICATION_PROMPT,
    classify_content,
    classify_document,
    match_course,
)
from services.ingestion.canvas_ingest import (  # noqa: F401
    ingest_canvas_files,
    link_pdfs_to_canvas_topics,
)
from services.ingestion.dispatch import dispatch_content as _dispatch_content  # noqa: F401
from services.ingestion.auto_generation import (  # noqa: F401, E402
    auto_summarize_titles,
    auto_generate_notes,
    auto_generate_flashcards,
    auto_generate_quiz,
    auto_prepare,
    auto_configure_course,
    _auto_generate_learning_content,
)

logger = logging.getLogger(__name__)

_PHASE_LABELS = {
    "uploaded": "Upload received",
    "extracting": "Extracting content",
    "classifying": "Classifying material",
    "dispatching": "Building workspace artifacts",
    "embedding": "Building semantic index",
    "completed": "Ready",
    "failed": "Failed",
}


def _prefer_extracted_title(job: IngestionJob, title: str | None) -> None:
    normalized = (title or "").strip()
    if job.source_type != "url" or not normalized:
        return
    if normalized == (job.url or "").strip():
        return
    job.original_filename = normalized


def _set_job_phase(
    job: IngestionJob,
    *,
    status: str,
    progress_percent: int,
    phase_label: str | None = None,
    embedding_status: str | None = None,
    nodes_created: int | None = None,
    error_message: str | None = None,
) -> None:
    job.status = status
    job.progress_percent = max(0, min(progress_percent, 100))
    job.phase_label = phase_label or _PHASE_LABELS.get(status)
    if embedding_status is not None:
        job.embedding_status = embedding_status
    if nodes_created is not None:
        job.nodes_created = nodes_created
    job.error_message = error_message


def _count_created_nodes(dispatch_result: Mapping[str, object] | None) -> int:
    if not dispatch_result:
        return 0
    total = 0
    for value in dispatch_result.values():
        if isinstance(value, int):
            total += value
    return total


def _snapshot_job_int(job: IngestionJob, field: str, default: int = 0) -> int:
    """Read scalar job fields without triggering ORM lazy-loading after rollback."""
    raw_value = job.__dict__.get(field, default)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return default


# ── Step 5 & 6: Full pipeline ──

async def run_ingestion_pipeline(
    db: AsyncSession,
    user_id: uuid.UUID,
    file_path: str | None = None,
    url: str | None = None,
    filename: str = "",
    course_id: uuid.UUID | None = None,
    file_bytes: bytes | None = None,
    pre_fetched_html: str | None = None,
    session_name: str | None = None,
) -> IngestionJob:
    """Run the full 7-step ingestion pipeline.

    Args:
        pre_fetched_html: When provided (e.g. from authenticated scraping),
            Step 2 uses this content directly instead of re-fetching the URL.
        session_name: Optional Playwright session name for authenticated
            Canvas API access during extraction.

    Returns the IngestionJob with results.
    """
    # Step 0: Content hash dedup (xxhash ~10x faster than SHA-256, ported from Crawl4AI)
    content_hash = None
    if file_bytes:
        try:
            import xxhash

            content_hash = xxhash.xxh64(file_bytes).hexdigest()
        except ImportError:
            content_hash = hashlib.sha256(file_bytes).hexdigest()
        # Check for duplicates
        duplicate_filters = [
            IngestionJob.content_hash == content_hash,
            IngestionJob.user_id == user_id,
            IngestionJob.status == "completed",
        ]
        if course_id:
            duplicate_filters.append(IngestionJob.course_id == course_id)

        existing = await db.execute(select(IngestionJob).where(*duplicate_filters))
        dupe = existing.scalar_one_or_none()
        if dupe:
            logger.info(f"Duplicate detected: {filename} (hash: {content_hash[:12]})")
            return dupe

    # Create job
    job = IngestionJob(
        user_id=user_id,
        source_type="file" if file_path else "url",
        original_filename=filename,
        url=url,
        file_path=file_path,
        content_hash=content_hash,
        course_id=course_id,
        course_preset=course_id is not None,
        status="uploaded",
        progress_percent=5,
        phase_label=_PHASE_LABELS["uploaded"],
        embedding_status="pending",
    )
    db.add(job)
    await db.flush()
    await db.commit()

    extracted = ""
    extracted_title = ""
    canvas_file_urls: list[dict] = []
    canvas_quiz_questions: list[dict] = []
    canvas_assignments_data: list[dict] = []

    try:
        # Step 1: MIME detection
        if filename:
            job.mime_type = detect_mime_type(filename, file_bytes)

        # Step 2: Content extraction
        _set_job_phase(job, status="extracting", progress_percent=20)
        await db.commit()

        # For Canvas URLs with auth, prefer deep Canvas REST API extraction
        if url and session_name:
            from services.scraper.canvas_detector import detect_canvas_url as _detect
            _cinfo = _detect(url)
            if _cinfo.is_canvas:
                from services.ingestion.document_loader import (
                    _try_canvas_api_deep, CanvasAuthExpiredError,
                )
                try:
                    deep_result = await _try_canvas_api_deep(url, session_name=session_name)
                except CanvasAuthExpiredError as auth_err:
                    # httpx returned 401 — session cookies may not work outside a real
                    # browser context (common with SSO/Okta-based Canvas logins).
                    # Try Playwright-based HTML extraction as a fallback before failing.
                    logger.warning(
                        "Canvas API returned 401 for %s (httpx). Trying Playwright fallback.",
                        url,
                    )
                    _playwright_fallback_ok = False
                    try:
                        from services.browser.automation import fetch_with_browser
                        from services.ingestion.document_loader import (
                            clean_soup_canvas_aware,
                            get_text_from_soup,
                        )
                        from bs4 import BeautifulSoup

                        fallback_html = await fetch_with_browser(url, session_name=session_name)
                        if fallback_html and len(fallback_html) > 200:
                            soup = BeautifulSoup(fallback_html, "lxml")
                            soup = clean_soup_canvas_aware(soup)
                            fallback_text = get_text_from_soup(soup)
                            if fallback_text:
                                extracted = fallback_text
                                _playwright_fallback_ok = True
                                logger.info(
                                    "Canvas Playwright fallback succeeded: %d chars for %s",
                                    len(extracted), url,
                                )
                    except Exception as fb_exc:
                        logger.debug("Canvas Playwright fallback also failed: %s", fb_exc)

                    if not _playwright_fallback_ok:
                        # Both approaches failed — mark session as expired and fail the job.
                        try:
                            from models.scrape import AuthSession
                            auth_result = await db.execute(
                                select(AuthSession).where(
                                    AuthSession.session_name == session_name,
                                    AuthSession.is_valid == True,  # noqa: E712
                                )
                            )
                            auth_session = auth_result.scalar_one_or_none()
                            if auth_session:
                                auth_session.is_valid = False
                                logger.info("Marked auth session %s as invalid", session_name)
                        except (sa.exc.SQLAlchemyError, OSError) as e:
                            logger.debug("Failed to invalidate auth session: %s", e)
                        _set_job_phase(
                            job,
                            status="failed",
                            progress_percent=20,
                            embedding_status="failed",
                            error_message=str(auth_err),
                        )
                        await db.commit()
                        return job
                else:
                    if deep_result:
                        extracted = deep_result.content
                        canvas_file_urls = deep_result.file_urls
                        canvas_quiz_questions = deep_result.quiz_questions
                        canvas_assignments_data = deep_result.assignments_data
                        logger.info(
                            "Canvas deep extraction: %d chars, %d pages, %d modules, %d files, %d quiz questions",
                            len(extracted), deep_result.pages_fetched,
                            deep_result.modules_found, len(canvas_file_urls),
                            len(canvas_quiz_questions),
                        )
                        # Auto-update course name from Canvas extraction
                        if deep_result.title and job.course_id:
                            try:
                                from models.course import Course
                                course_result = await db.execute(
                                    sa.select(Course).where(Course.id == job.course_id)
                                )
                                course_obj = course_result.scalar_one_or_none()
                                if course_obj:
                                    course_obj.name = deep_result.title
                                    logger.info("Auto-set course name from Canvas: %s", deep_result.title)
                            except (
                                sa.exc.SQLAlchemyError,
                                ValueError,
                                AttributeError,
                                TypeError,
                            ) as name_err:
                                logger.debug("Could not auto-set course name: %s", name_err)

        if not extracted and pre_fetched_html:
            # Authenticated scraping: content already fetched, parse HTML to text
            # Use Canvas-aware cleaning that preserves content containers
            from services.ingestion.document_loader import (
                clean_soup_canvas_aware,
                extract_title,
                get_text_from_soup,
            )
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(pre_fetched_html, "lxml")
            extracted_title = extract_title(soup, url=url)
            content_root = clean_soup_canvas_aware(soup)
            extracted = get_text_from_soup(content_root, title=extracted_title)
            _prefer_extracted_title(job, extracted_title)

        if not extracted:
            extracted_title, extracted = await extract_content_with_title(
                file_path, url, job.mime_type or "", session_name=session_name,
            )
            _prefer_extracted_title(job, extracted_title)
        job.extracted_markdown = extracted

        if not extracted:
            _set_job_phase(
                job,
                status="failed",
                progress_percent=20,
                embedding_status="failed",
                error_message="No content could be extracted",
            )
            await db.commit()
            return job

        # Step 3: 3-tier classification
        _set_job_phase(job, status="classifying", progress_percent=45)
        await db.commit()
        job.content_category, job.classification_method = await classify_document(
            extracted,
            filename,
        )

        # Step 4: Course matching (if not preset)
        if not course_id:
            matched_id = await match_course(db, filename, extracted, user_id)
            if matched_id:
                job.course_id = matched_id

        # Step 5: Status update
        _set_job_phase(job, status="dispatching", progress_percent=70)
        await db.commit()

        # Step 6: Dispatch to business tables
        dispatch_result = await _dispatch_content(db, job)
        job.dispatched = True
        job.dispatched_to = dispatch_result
        nodes_created = _count_created_nodes(dispatch_result)
        needs_embedding = bool((dispatch_result or {}).get("content_tree"))
        if needs_embedding:
            _set_job_phase(
                job,
                status="embedding",
                progress_percent=90,
                embedding_status="pending",
                nodes_created=nodes_created,
            )
        else:
            _set_job_phase(
                job,
                status="completed",
                progress_percent=100,
                embedding_status="completed",
                nodes_created=nodes_created,
            )
        await db.commit()

    except Exception as e:
        # Intentional catch-all: never let unexpected errors bypass job state
        # persistence; all failures must resolve to a terminal "failed" job.
        try:
            await db.rollback()
        except (sa.exc.SQLAlchemyError, OSError):
            logger.debug("Rollback after ingestion failure also failed", exc_info=True)
        last_progress = _snapshot_job_int(job, "progress_percent", 0)
        last_nodes = _snapshot_job_int(job, "nodes_created", 0)
        _set_job_phase(
            job,
            status="failed",
            progress_percent=last_progress,
            embedding_status="failed",
            nodes_created=last_nodes,
            error_message=str(e)[:500],
        )
        logger.exception("Ingestion pipeline failed")
        try:
            db.add(job)
            await db.commit()
        except (sa.exc.SQLAlchemyError, OSError):
            logger.exception("Failed to persist ingestion failure")

    await db.flush()
    # Attach discovered Canvas file URLs and quiz questions for the caller to process
    job._canvas_file_urls = canvas_file_urls if canvas_file_urls else []
    job._canvas_quiz_questions = canvas_quiz_questions if canvas_quiz_questions else []
    # Attach Canvas assignments data for deadline extraction in _dispatch_content
    job._canvas_assignments_data = canvas_assignments_data if canvas_assignments_data else []
    return job
