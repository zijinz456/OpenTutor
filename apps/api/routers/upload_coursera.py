"""Coursera ZIP upload endpoint (Phase 14 T3).

Accepts a user-supplied ZIP of locally-downloaded Coursera lecture assets
(``.vtt`` transcripts + ``.pdf`` slides), pairs them, merges each pair into
a synthetic ``.coursera.md`` blob, and drives each blob through the shared
``run_ingestion_pipeline``. One child ``IngestionJob`` per lecture.

Critical Phase 14 T5 fix: ``build_syllabus`` fires ONCE for the whole batch
(scheduled as a background task with a 2s delay) instead of per-job, because
N lectures would otherwise trigger N× redundant LLM calls + overwrites.

Idempotency is keyed on xxhash of the raw ZIP bytes, persisted to
``Course.metadata_["coursera_import"]["zip_hash"]``. Re-uploading the same
ZIP returns ``status="already_imported"`` without creating new jobs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import async_session, get_db
from libs.exceptions import ValidationError
from models.user import User
from schemas.coursera import CourseraUploadResponse
from services.agent.background_runtime import track_background_task
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.ingestion.coursera_adapter import (
    CourseraAdapterError,
    merge_lecture_markdown,
    parse_coursera_zip,
)
from services.ingestion.pipeline import run_ingestion_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()

# Size cap applies to the compressed ZIP. The adapter enforces separate
# caps (2 GiB uncompressed, 500 file count) on the inner entries.
_MAX_ZIP_BYTES = 500 * 1024 * 1024  # 500 MiB

# Post-batch syllabus delay — matches `dispatch.py` pattern so the caller's
# commit on the content tree is visible before `syllabus_builder` reads it.
_SYLLABUS_DELAY_SECONDS = 2.0

# Phase 14 T6: when a Coursera import ships more lectures than this, clamp
# the generated roadmap to the first week only and lock the rest behind
# ``Course.metadata_["locked_weeks"]``. The user unlocks weeks manually
# from the UI — avoids a 100-node firehose for multi-week specializations.
_ADHD_LECTURE_CLAMP_THRESHOLD = 20


@router.post(
    "/upload/coursera",
    summary="Upload a Coursera ZIP",
    description=(
        "Parse a ZIP of locally-downloaded Coursera lectures (VTT + PDF "
        "pairs) and ingest one ``IngestionJob`` per lecture."
    ),
    response_model=CourseraUploadResponse,
)
async def upload_coursera_zip(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseraUploadResponse:
    """Ingest a Coursera ZIP into the existing 7-step pipeline."""
    try:
        cid = uuid.UUID(course_id)
    except ValueError as e:
        raise ValidationError("Invalid course_id") from e

    # 404 when the course is missing/not owned — raised as AppError(status=404).
    course = await get_course_or_404(db, cid, user_id=user.id)

    zip_bytes = await file.read()
    if not zip_bytes:
        raise ValidationError("Empty upload")
    if len(zip_bytes) > _MAX_ZIP_BYTES:
        raise ValidationError(
            f"ZIP too large: {len(zip_bytes)} bytes > {_MAX_ZIP_BYTES} bytes cap"
        )

    zip_hash = _zip_digest(zip_bytes)

    # Idempotency: skip the whole batch when the same archive was already ingested.
    prior = (course.metadata_ or {}).get("coursera_import") or {}
    if prior.get("zip_hash") == zip_hash:
        logger.info(
            "coursera_upload_skipped_idempotent course_id=%s zip_hash=%s",
            cid,
            zip_hash[:12],
        )
        return CourseraUploadResponse(
            course_id=str(cid),
            lectures_total=int(prior.get("lectures_total", 0)),
            lectures_paired=int(prior.get("lectures_paired", 0)),
            lectures_vtt_only=int(prior.get("lectures_vtt_only", 0)),
            lectures_pdf_only=int(prior.get("lectures_pdf_only", 0)),
            job_ids=[],
            status="already_imported",
        )

    # Parse + validate. CourseraAdapterError maps to HTTP 400 with structured body.
    try:
        pairs = parse_coursera_zip(zip_bytes)
    except CourseraAdapterError as err:
        raise ValidationError(
            f"Coursera ZIP rejected: {err.reason}. Hint: {err.hint}"
        ) from err

    lectures_paired = sum(1 for p in pairs if p.vtt_path and p.pdf_path)
    lectures_vtt_only = sum(1 for p in pairs if p.vtt_path and not p.pdf_path)
    lectures_pdf_only = sum(1 for p in pairs if p.pdf_path and not p.vtt_path)

    # Zip stem — stable per-upload label used to prefix every synthetic
    # ``.coursera.md`` filename so the content-tree ``source_file`` column
    # carries enough structure for the T6 week-prefix filter. Derive from
    # the uploaded filename when available; fall back to the hash so
    # pipelined filenames never collide across different uploads.
    zip_stem = _zip_stem(file.filename, zip_hash)

    os.makedirs(settings.upload_dir, exist_ok=True)

    job_ids: list[str] = []
    for pair in pairs:
        md_filename, md_bytes = merge_lecture_markdown(pair)
        # Prefix with ``{zip_stem}/Week-N/`` so that the content_tree row's
        # ``source_file`` (copied from ``original_filename`` in dispatch)
        # starts with the week prefix the T6 clamp filters on. Pipeline
        # classification regex is substring-based, so a ``/`` in the name
        # is benign for ``.coursera.md`` matching.
        prefixed_name = f"{zip_stem}/Week-{pair.week_index}/{md_filename}"
        save_path = _write_synthetic_markdown(zip_hash, md_filename, md_bytes)
        try:
            job = await run_ingestion_pipeline(
                db=db,
                user_id=user.id,
                file_path=save_path,
                filename=prefixed_name,
                course_id=cid,
                file_bytes=md_bytes,
            )
            # Tag the job ``source_type="coursera"`` so downstream analytics
            # and the syllabus gate can distinguish Coursera imports. The
            # pipeline sets ``"file"`` by default; dispatch has already run
            # with that value and intentionally bypasses the per-job URL
            # syllabus trigger — we fire one batch syllabus below instead.
            job.source_type = "coursera"
            await db.commit()
        except Exception:
            # Clean up the synthetic file on pipeline failure; re-raise.
            _safe_unlink(save_path)
            raise

        job_ids.append(str(job.id))

    # ── Phase 14 T6: ADHD clamp for > 20 lectures ─────────────────────
    lectures_total = len(pairs)
    weeks_present = sorted({p.week_index for p in pairs})
    if lectures_total > _ADHD_LECTURE_CLAMP_THRESHOLD and weeks_present:
        min_week = weeks_present[0]
        locked_weeks: list[int] = [w for w in weeks_present if w != min_week]
        week_prefix = f"{zip_stem}/Week-{min_week}/"
        roadmap_scope: dict | None = {"week_prefix_filter": week_prefix}
        logger.info(
            "coursera_adhd_clamp course_id=%s lectures=%d first_week=%d locked=%s",
            cid,
            lectures_total,
            min_week,
            locked_weeks,
        )
    else:
        locked_weeks = []
        roadmap_scope = None

    # Persist the import record on the course so re-upload is a no-op.
    course.metadata_ = {
        **(course.metadata_ or {}),
        "coursera_import": {
            "zip_hash": zip_hash,
            "lectures_total": lectures_total,
            "lectures_paired": lectures_paired,
            "lectures_vtt_only": lectures_vtt_only,
            "lectures_pdf_only": lectures_pdf_only,
            "imported_at": datetime.now(timezone.utc).isoformat(),
        },
        "locked_weeks": locked_weeks,
    }
    await db.commit()

    # T5: schedule ONE syllabus build for the whole batch, regardless of how
    # many child jobs we created. Own DB session (detached fire-and-forget).
    # T6: forward the ADHD clamp's scope so build_syllabus only reads rows
    # from the first week when the course is over-sized.
    track_background_task(
        asyncio.create_task(_post_coursera_syllabus(cid, roadmap_scope=roadmap_scope))
    )

    return CourseraUploadResponse(
        course_id=str(cid),
        lectures_total=lectures_total,
        lectures_paired=lectures_paired,
        lectures_vtt_only=lectures_vtt_only,
        lectures_pdf_only=lectures_pdf_only,
        job_ids=job_ids,
        status="created",
    )


# ── Helpers ────────────────────────────────────────────────────────────


def _zip_digest(zip_bytes: bytes) -> str:
    """Return a stable content hash for a ZIP — xxhash when available."""
    try:
        # xxhash is ~10× faster than sha256 and is already a pipeline dep.
        import xxhash

        return xxhash.xxh64(zip_bytes).hexdigest()
    except ImportError:
        return hashlib.sha256(zip_bytes).hexdigest()


def _zip_stem(upload_filename: str | None, zip_hash: str) -> str:
    """Return a filesystem-safe stem derived from the uploaded ZIP name.

    The stem becomes the leading component of every lecture's
    ``source_file`` path, which the T6 ADHD clamp uses as a filter prefix.
    Falls back to a short hash slice when the upload has no usable name
    (e.g. anonymous streams in integration tests).
    """
    if upload_filename:
        base = upload_filename.replace("\\", "/").rsplit("/", 1)[-1]
        if base.lower().endswith(".zip"):
            base = base[:-4]
        safe = re.sub(r"[^\w.\-]", "_", base).strip("._-")
        if safe:
            return safe[:60]
    return f"coursera_{zip_hash[:12]}"


def _write_synthetic_markdown(zip_hash: str, md_filename: str, md_bytes: bytes) -> str:
    """Spill merged markdown to ``settings.upload_dir`` so the pipeline can read it."""
    safe_name = re.sub(r"[^\w.\-]", "_", md_filename) or "lecture.coursera.md"
    safe_name = safe_name[:255]
    save_path = os.path.join(
        settings.upload_dir, f"coursera_{zip_hash[:12]}_{safe_name}"
    )
    Path(save_path).write_bytes(md_bytes)
    return save_path


def _safe_unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        logger.warning("Failed to remove synthetic markdown: %s", path)


async def _post_coursera_syllabus(
    course_id: uuid.UUID,
    delay: float = _SYLLABUS_DELAY_SECONDS,
    roadmap_scope: dict | None = None,
) -> None:
    """Trigger ``build_syllabus`` once for the entire Coursera batch.

    Runs on its own DB session so it survives the request's session being
    closed. Failures are logged and swallowed — the ingest itself has already
    succeeded and the roadmap is best-effort.

    When ``roadmap_scope`` is provided, it is forwarded to ``build_syllabus``
    verbatim — currently used for the T6 ADHD clamp (``week_prefix_filter``)
    so over-sized courses only roadmap the first week.
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
                    "coursera_syllabus_skip reason=builder_returned_none course_id=%s",
                    course_id,
                )
                return
            await persist_syllabus(bg_db, course_id, syllabus)
            await bg_db.commit()
    except Exception:  # noqa: BLE001 — best-effort background work; never raise
        logger.exception("coursera_syllabus_failed course_id=%s", course_id)


# ── Internal reference for test monkeypatching ─────────────────────────
# Tests replace ``build_syllabus`` via ``monkeypatch.setattr`` against either
# the syllabus_builder module OR this module's direct import. Expose a bound
# name so tests can patch it without reaching into lazily-imported code.
_post_coursera_syllabus_func = _post_coursera_syllabus


async def list_outstanding_tasks() -> set[asyncio.Task]:
    """Diagnostic helper (unused at runtime): list tasks tracked by the runtime."""
    # Intentionally lightweight — see ``background_runtime._background_tasks``.
    from services.agent.background_runtime import _background_tasks

    return set(_background_tasks)
