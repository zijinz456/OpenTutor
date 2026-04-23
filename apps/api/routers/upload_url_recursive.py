"""Recursive URL ingest endpoint (§14.5 v2.5 T3).

``POST /api/content/upload/url/recursive`` drives ``crawl_urls`` (T1) with the
T2 robots/rate-limit wrappers and funnels every ``status="ok"`` page through
the shared ``run_ingestion_pipeline`` as a synthetic ``.recursive.md`` blob.
One ``IngestionJob`` per crawled page; one post-batch ``build_syllabus``
trigger (2s delay, mirroring ``upload_coursera.py``) instead of N per-job
calls that would thrash the LLM and overwrite roadmaps.

A module-level ``_ACTIVE_CRAWLS: set[str]`` prevents two concurrent recursive
crawls on the same ``course_id`` from gang-ing up on the shared rate limiter
and each other's dedup state. The second request gets a structured 409.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session, get_db
from libs.exceptions import ConflictError
from models.course import Course
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.crawler.recursive_crawler import CrawledPage, crawl_urls
from services.ingestion.document_loader_html import clean_soup, get_text_from_soup
from services.ingestion.pipeline import run_ingestion_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()

# Module-level guard: every active crawl registers its ``course_id`` here so a
# concurrent request to the same course short-circuits with 409. Set is fine —
# FastAPI runs every handler on the same event loop, so the read-then-add
# sequence below is effectively atomic (no preemption between the two lines).
_ACTIVE_CRAWLS: set[str] = set()

# Crawl caps — T3 defaults, deliberately matching the T1 header so the router
# doesn't re-argue policy with the crawler. Override surface is intentionally
# small; larger crawls should go through a dedicated batch endpoint later.
_MAX_PAGES = 100
_MAX_TOTAL_HTML_BYTES = 500 * 1024 * 1024  # 500 MiB

# Post-batch syllabus delay — mirrors ``upload_coursera.py`` so whatever
# commits the router emitted on the content tree are visible to the syllabus
# builder's own session.
_SYLLABUS_DELAY_SECONDS = 2.0

# T6 ADHD clamp — when a single crawl ingests more pages than this, the
# router restricts the roadmap to the largest "section" (grouped by the
# first two segments of each URL's path) and pushes every other prefix into
# ``Course.metadata_["locked_sections"]``. Mirrors Phase 14 Coursera's
# ``_ADHD_LECTURE_CLAMP_THRESHOLD`` so both ingest paths share the same
# mental model for the user.
_ADHD_PAGE_CLAMP_THRESHOLD = 20

# Number of leading URL path segments that define a "section" for the T6
# clamp. Two segments (e.g. ``/tutorial/intro/``) is the sweet spot: enough
# to split a docs site into coherent sections, short enough not to fragment
# a single section into per-page groups.
_SECTION_PATH_DEPTH = 2


class RecursiveUrlRequest(BaseModel):
    """Request body for ``POST /upload/url/recursive``."""

    url: str = Field(..., description="Seed URL (http/https)")
    course_id: str = Field(..., description="Course UUID")
    # ``Literal`` forces FastAPI/pydantic to return a 422 validation error
    # for out-of-range depths rather than letting them flow into the crawler
    # and produce a silently oversized BFS.
    max_depth: Literal[1, 2, 3] = 2
    path_prefix: str | None = Field(
        default=None,
        description="Optional URL path prefix filter (tighter than same-origin)",
    )


class RecursiveUrlResponse(BaseModel):
    """Response body for ``POST /upload/url/recursive``."""

    course_id: str
    pages_crawled: int = Field(..., ge=0)
    pages_skipped_robots: int = Field(..., ge=0)
    pages_skipped_origin: int = Field(..., ge=0)
    pages_skipped_dedup: int = Field(..., ge=0)
    pages_fetch_failed: int = Field(..., ge=0)
    job_ids: list[str] = Field(
        default_factory=list,
        description="IngestionJob UUIDs, one per successfully crawled page",
    )


@router.post(
    "/upload/url/recursive",
    summary="Recursive URL crawl + ingest",
    description=(
        "BFS-crawl a seed URL within its origin (or a tighter path prefix) "
        "and ingest every reachable HTML page as a separate IngestionJob. "
        "Schedules a single post-batch syllabus rebuild."
    ),
    response_model=RecursiveUrlResponse,
)
async def upload_url_recursive(
    body: RecursiveUrlRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RecursiveUrlResponse:
    """Recursively crawl ``body.url`` and create one IngestionJob per page."""
    # URL shape gate: a 400 here means "syntactically not a URL", distinct
    # from the 422 pydantic returns for bad ``max_depth``. Using HTTPException
    # directly because ``AppError`` has no 400 subclass in this codebase.
    if not _is_http_url(body.url):
        raise HTTPException(status_code=400, detail="URL must be http:// or https://")

    try:
        cid = uuid.UUID(body.course_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid course_id") from exc

    # 404 if the course is missing or not owned — consistent with every
    # other /upload/* route.
    await get_course_or_404(db, cid, user_id=user.id)

    # Concurrency guard. Check-then-add is safe because FastAPI's async
    # runtime does not preempt coroutines between plain statements.
    cid_key = str(cid)
    if cid_key in _ACTIVE_CRAWLS:
        raise ConflictError("Recursive crawl already in progress for this course")
    _ACTIVE_CRAWLS.add(cid_key)

    pages_crawled = 0
    pages_skipped_robots = 0
    pages_skipped_origin = 0
    pages_skipped_dedup = 0
    pages_fetch_failed = 0
    job_ids: list[str] = []
    # Track which "section" (first-two-path-segments prefix) each successful
    # page belongs to so the T6 ADHD clamp can group them without re-querying
    # the DB. Ordered list preserves the crawl order — we use it below to
    # break ties in favour of the seed's section.
    crawled_section_prefixes: list[str] = []

    os.makedirs(settings.upload_dir, exist_ok=True)

    try:
        async for page in crawl_urls(
            seed_urls=[body.url],
            max_depth=body.max_depth,
            same_origin=True,
            path_prefix=body.path_prefix,
            max_pages=_MAX_PAGES,
            max_total_html_bytes=_MAX_TOTAL_HTML_BYTES,
        ):
            # Account for every yielded event so the response mirrors what
            # the crawler actually did — makes the UI reportable and lets
            # tests assert against an unambiguous status breakdown.
            if page.status == "skip_robots":
                pages_skipped_robots += 1
                continue
            if page.status == "skip_origin":
                pages_skipped_origin += 1
                continue
            if page.status == "skip_dedup":
                pages_skipped_dedup += 1
                continue
            if page.status == "fetch_fail":
                pages_fetch_failed += 1
                continue
            if page.status != "ok" or page.html is None:
                # ``skip_prefix`` / ``skip_depth`` — not surfaced in the
                # response breakdown per plan scope. Counted implicitly by
                # the absence from every other bucket.
                continue

            job_id = await _ingest_page(db, user_id=user.id, course_id=cid, page=page)
            if job_id is not None:
                pages_crawled += 1
                job_ids.append(job_id)
                crawled_section_prefixes.append(_url_section_prefix(page.url))
    finally:
        _ACTIVE_CRAWLS.discard(cid_key)

    # T6: ADHD clamp — when a single crawl ingests > 20 pages, scope the
    # syllabus to just one "section" (by URL path prefix) and persist the
    # rest in ``Course.metadata_["locked_sections"]`` for a manual unlock
    # UX. Mirrors Phase 14 Coursera's ``locked_weeks`` contract exactly.
    roadmap_scope, locked_sections = _compute_adhd_clamp(
        seed_url=body.url,
        section_prefixes=crawled_section_prefixes,
    )
    await _persist_locked_sections(db, cid, locked_sections)

    # T5: one post-batch syllabus build for the whole crawl, fire-and-forget
    # on its own session so request teardown does not cancel it. T6 forwards
    # the (possibly-``None``) clamp scope so over-sized courses only roadmap
    # the first section.
    if job_ids:
        asyncio.create_task(_post_recursive_syllabus(cid, roadmap_scope=roadmap_scope))

    return RecursiveUrlResponse(
        course_id=str(cid),
        pages_crawled=pages_crawled,
        pages_skipped_robots=pages_skipped_robots,
        pages_skipped_origin=pages_skipped_origin,
        pages_skipped_dedup=pages_skipped_dedup,
        pages_fetch_failed=pages_fetch_failed,
        job_ids=job_ids,
    )


# ── Helpers ────────────────────────────────────────────────────────────


def _is_http_url(url: str) -> bool:
    """Cheap syntactic URL gate.

    Rejects whitespace, non-http/https schemes, and anything without a host.
    Deeper SSRF/DNS checks live in the crawler and the pipeline — this is
    just the 400-vs-422 dividing line for malformed input.
    """
    candidate = (url or "").strip()
    if not candidate or " " in candidate:
        return False
    # urlparse is lenient — inspect scheme explicitly.
    lower = candidate.lower()
    if not (lower.startswith("http://") or lower.startswith("https://")):
        return False
    # Minimal "has a netloc" heuristic.
    rest = candidate.split("://", 1)[1]
    return bool(rest) and not rest.startswith("/")


def _url_section_prefix(url: str, depth: int = _SECTION_PATH_DEPTH) -> str:
    """Return the leading ``depth`` path segments of ``url``, slash-terminated.

    Used as a "section" key for both the synthetic filename (so the T6
    clamp's ``path_prefix_filter`` can slice the content tree by prefix)
    and for the ADHD grouping itself. Segments are taken verbatim from the
    URL path — no lower-casing, no stripping — to preserve the exact string
    that ``source_file.startswith(prefix)`` will later compare against.

    Empty/root URLs collapse to ``"_root/"`` so the prefix is never empty
    (an empty ``startswith`` prefix would match every row and silently
    disable the clamp).
    """
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if not parts:
        return "_root/"
    head = parts[:depth]
    return "/".join(head) + "/"


def _synthetic_filename(url: str) -> str:
    """Filename under which a crawled page is stored in the pipeline.

    Stable on the canonical URL so re-crawling the same URL dedups via the
    pipeline's ``content_hash`` column rather than creating a second row.

    The filename is prefixed with the URL's first ``_SECTION_PATH_DEPTH``
    path segments so every ``CourseContentTree.source_file`` stored by the
    pipeline starts with that prefix. The T6 ADHD clamp filters on that
    prefix via ``roadmap_scope={"path_prefix_filter": ...}`` — exactly how
    Phase 14 Coursera uses ``Week-N/`` prefixes.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    prefix = _url_section_prefix(url)
    return f"{prefix}page-{digest}.recursive.md"


def _html_to_markdown(html: str, url: str) -> str:
    """Strip boilerplate and return plain-text suitable for the pipeline.

    Uses the existing ``clean_soup`` / ``get_text_from_soup`` helpers from the
    file-upload HTML extractor so behavior matches the non-recursive
    ``/upload/url`` endpoint. A tiny front-matter header preserves the source
    URL for later debugging; markdown downstream tooling treats it as text.
    """
    soup = BeautifulSoup(html, "html.parser")
    cleaned = clean_soup(soup)
    body_text = get_text_from_soup(cleaned)
    header = f"<!-- source: {url} -->\n\n"
    return header + body_text


async def _ingest_page(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    page: CrawledPage,
) -> str | None:
    """Spill a crawled page to disk and run it through the ingestion pipeline.

    Returns the IngestionJob id on success, or ``None`` if the pipeline
    failed in a way we don't want to abort the whole crawl over.
    """
    assert page.html is not None  # guarded by the caller

    md_text = _html_to_markdown(page.html, page.url)
    md_bytes = md_text.encode("utf-8")
    filename = _synthetic_filename(page.url)
    # Prefix the on-disk name so synthetic files from different crawls can't
    # collide in ``settings.upload_dir`` after sanitization.
    safe_name = re.sub(r"[^\w.\-]", "_", filename)[:255]
    save_path = os.path.join(
        settings.upload_dir, f"recursive_{course_id.hex[:12]}_{safe_name}"
    )
    Path(save_path).write_bytes(md_bytes)

    try:
        job = await run_ingestion_pipeline(
            db=db,
            user_id=user_id,
            file_path=save_path,
            filename=filename,
            course_id=course_id,
            file_bytes=md_bytes,
        )
        # Tag provenance via raw UPDATE instead of attribute assignment.
        # The pipeline may detach the returned job from the outer session
        # (CourseContentTree relationships load lazily during attribute
        # access, hitting DetachedInstanceError when touched post-commit).
        # An UPDATE sidesteps ORM-session bookkeeping entirely.
        from sqlalchemy import update
        from models.ingestion import IngestionJob
        job_id = job.id  # primary key is already loaded, safe to read
        await db.execute(
            update(IngestionJob)
            .where(IngestionJob.id == job_id)
            .values(source_type="url_recursive", url=page.url)
        )
        await db.commit()
    except Exception:
        # One flaky page must not torpedo a 50-page crawl. Clean up the
        # synthetic spill and move on; the counter bucket will record the
        # failure via the crawler's ``fetch_fail`` status on next pass.
        _safe_unlink(save_path)
        logger.exception("recursive_ingest_page_failed url=%s", page.url)
        return None

    return str(job_id)


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        logger.warning("Failed to remove synthetic markdown: %s", path)


def _compute_adhd_clamp(
    *,
    seed_url: str,
    section_prefixes: list[str],
) -> tuple[dict | None, list[str]]:
    """Decide whether to clamp the roadmap to a single URL section.

    Returns a ``(roadmap_scope, locked_sections)`` pair:

    - ``roadmap_scope`` — either ``None`` (no clamp, < threshold pages) or
      ``{"path_prefix_filter": "<first-section-prefix>"}`` ready to hand to
      ``build_syllabus``.
    - ``locked_sections`` — list of path prefixes that were pushed out of
      the initial roadmap; persisted on ``Course.metadata_`` so the UI can
      render an "Unlock" control against each. Empty when no clamp fired.

    The "first section" is the prefix with the most crawled pages; ties
    break in favour of the seed URL's own prefix so a user who paste-ed
    ``/tutorial/intro/`` never wakes up with their roadmap scoped to some
    other section that happened to contain the same page count.
    """
    if len(section_prefixes) <= _ADHD_PAGE_CLAMP_THRESHOLD:
        return None, []

    counts = Counter(section_prefixes)
    seed_prefix = _url_section_prefix(seed_url)

    # ``most_common()`` returns an implementation-defined tie-order. Prefer
    # the seed prefix when it's tied for first place so the user-chosen
    # entrypoint wins deterministically.
    max_count = max(counts.values())
    tied = [prefix for prefix, c in counts.items() if c == max_count]
    if seed_prefix in tied:
        first_prefix = seed_prefix
    else:
        # Sort for determinism — otherwise different dict orderings across
        # Python builds could pick different winners from the same crawl.
        first_prefix = sorted(tied)[0]

    locked = sorted(prefix for prefix in counts if prefix != first_prefix)
    roadmap_scope: dict | None = {"path_prefix_filter": first_prefix}
    logger.info(
        "recursive_adhd_clamp pages=%d first_prefix=%s locked=%s",
        sum(counts.values()),
        first_prefix,
        locked,
    )
    return roadmap_scope, locked


async def _persist_locked_sections(
    db: AsyncSession,
    course_id: uuid.UUID,
    locked_sections: list[str],
) -> None:
    """Write ``Course.metadata_["locked_sections"]`` and commit.

    Always writes the key (possibly an empty list) so the UI can trust its
    presence; mirrors Phase 14 Coursera which writes ``locked_weeks=[]``
    under the clamp threshold rather than leaving the key absent.
    """
    course = await db.get(Course, course_id)
    if course is None:
        # Concurrently-deleted course — nothing to write. The outer handler
        # will still attempt the syllabus build, which will see no rows and
        # return ``None`` harmlessly.
        logger.warning(
            "recursive_locked_sections_skip reason=course_missing course_id=%s",
            course_id,
        )
        return
    course.metadata_ = {
        **(course.metadata_ or {}),
        "locked_sections": locked_sections,
    }
    await db.commit()


async def _post_recursive_syllabus(
    course_id: uuid.UUID,
    delay: float = _SYLLABUS_DELAY_SECONDS,
    roadmap_scope: dict | None = None,
) -> None:
    """Trigger ``build_syllabus`` once after the crawl batch completes.

    Runs on its own DB session so it outlives the request; failures are
    logged and swallowed — the ingest itself already committed every job.

    ``roadmap_scope`` is forwarded to ``build_syllabus`` verbatim; used by
    the T6 ADHD clamp to restrict the roadmap to a single path prefix when
    the crawl ingested more than ``_ADHD_PAGE_CLAMP_THRESHOLD`` pages.
    """
    await asyncio.sleep(delay)
    try:
        from services.curriculum.syllabus_builder import build_syllabus
        from services.curriculum.syllabus_persist import persist_syllabus

        async with async_session() as bg_db:
            syllabus = await build_syllabus(
                bg_db, course_id, roadmap_scope=roadmap_scope
            )
            if syllabus is None:
                logger.info(
                    "recursive_syllabus_skip reason=builder_returned_none course_id=%s",
                    course_id,
                )
                return
            await persist_syllabus(bg_db, course_id, syllabus)
            await bg_db.commit()
    except Exception:  # noqa: BLE001 — best-effort background work
        logger.exception("recursive_syllabus_failed course_id=%s", course_id)


# Exposed for test monkeypatching: the integration tests replace this with a
# spy to verify the batch trigger fires exactly once per crawl.
_post_recursive_syllabus_func = _post_recursive_syllabus
