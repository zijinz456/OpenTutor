"""Upload helper functions and background processing tasks.

Split from upload.py to keep file sizes manageable.
Contains: filename helpers, scrape fixture loading, Canvas auth helpers,
and background tasks (embedding, auto-generate, quiz import).
"""

import asyncio
import logging
import os
import re
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from config import settings
from libs.exceptions import AppError, NotFoundError
from libs.url_validation import validate_url, validate_url_dns
from database import async_session
from models.ingestion import IngestionJob
from models.practice import PracticeProblem
from models import scrape as models_scrape
from services.ingestion.pipeline import _set_job_phase
from services.llm.readiness import ensure_llm_ready

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backward-compatible aliases used by unit tests and older imports.
# ---------------------------------------------------------------------------
_validate_url = validate_url
_validate_url_dns = validate_url_dns


# ---------------------------------------------------------------------------
# Filename / URL helpers
# ---------------------------------------------------------------------------

def _safe_filename(filename: str) -> str:
    """Sanitize user-provided filename to prevent path traversal."""
    base = os.path.basename(filename)
    cleaned = re.sub(r'[^\w.\-]', '_', base)
    return (cleaned or "unnamed")[:255]


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


def _derive_filename(url: str) -> str:
    """Derive a meaningful filename from a URL."""
    from services.scraper.canvas_detector import detect_canvas_url

    canvas_info = detect_canvas_url(url)
    if canvas_info.is_canvas:
        return canvas_info.friendly_name

    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if segments:
        name = segments[-1]
        # If no file extension, assume HTML (we're scraping a web page)
        if "." not in name:
            name += ".html"
        return name
    return (parsed.hostname or "webpage") + ".html"


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
            except (OSError, ConnectionError, TimeoutError, ValueError) as e:
                logger.debug("Canvas auth fetch via ScrapeSource failed: %s", e)
        return None

    session_name = auth_session.session_name
    try:
        from services.browser.automation import cascade_fetch
        html = await cascade_fetch(url, require_auth=True, session_name=session_name)
        if html and len(html) > 200:
            return html
    except (OSError, ConnectionError, TimeoutError, ValueError) as e:
        logger.debug("Canvas auth fetch via AuthSession failed: %s", e)

    return None


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _background_auto_generate(course_id: uuid.UUID, user_id: uuid.UUID):
    """Fire-and-forget: auto-generate starter quiz + flashcards + notes after ingestion."""
    try:
        await ensure_llm_ready("Auto-generated starter study assets")
    except (AppError, OSError) as exc:
        logger.debug("Skipping starter asset generation for course %s: %s", course_id, exc)
        return

    try:
        from services.ingestion.pipeline import auto_prepare
        summary = await auto_prepare(async_session, course_id, user_id)
        logger.info("auto_prepare complete for course %s: %s", course_id, summary)
    except (SQLAlchemyError, AppError, ValueError, OSError):
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
    except (SQLAlchemyError, ValueError, KeyError, TypeError):
        logger.exception("Canvas quiz import failed (best-effort)")
        return 0


async def _background_embed(course_id: uuid.UUID, job_id: uuid.UUID, user_id: uuid.UUID | None = None):
    """Fire-and-forget: compute embeddings + auto-generate assets in parallel."""

    async def _do_embed():
        from services.embedding.content import embed_course_content
        from services.embedding.registry import is_noop_provider
        async with async_session() as db:
            job = await db.get(IngestionJob, job_id)
            skipped = is_noop_provider()
            if job and not skipped:
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
                    embedding_status="skipped" if skipped else "completed",
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
    except (SQLAlchemyError, AppError, OSError, ValueError) as e:
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
        except SQLAlchemyError:
            logger.exception("Failed to persist embedding failure for job %s", job_id)
        logger.exception("Background embedding failed for job %s", job_id)


def start_background_canvas_pipeline(
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    canvas_file_urls: list[str],
    scrape_session_name: str,
    canvas_domain: str,
) -> None:
    """Launch the background Canvas file ingestion + post-processing pipeline."""
    from services.ingestion.pipeline import (
        ingest_canvas_files, link_pdfs_to_canvas_topics,
        auto_summarize_titles, auto_prepare,
    )
    from services.agent.background_runtime import track_background_task

    async def _pipeline():
        await ingest_canvas_files(
            db_factory=async_session, user_id=user_id, course_id=course_id,
            file_urls=canvas_file_urls, session_name=scrape_session_name,
            canvas_domain=canvas_domain,
        )
        await link_pdfs_to_canvas_topics(
            db_factory=async_session, course_id=course_id, file_urls=canvas_file_urls,
        )
        await auto_summarize_titles(db_factory=async_session, course_id=course_id)
        await auto_prepare(db_factory=async_session, course_id=course_id, user_id=user_id)

    track_background_task(asyncio.create_task(_pipeline()))
