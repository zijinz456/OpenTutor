"""Screenshot-to-Drill upload endpoint (Phase 4 T2).

Thin HTTP wrapper around ``services.screenshot.vision_extractor``:

* validates the uploaded image (MIME + ≤5 MiB size cap),
* user-scoped token-bucket rate limit (5 req/min),
* user-scoped TTL cache keyed on ``sha256(bytes)[:16]`` so re-uploading
  the same screenshot within 10 minutes is free (zero LLM calls),
* looks up the top-5 ``KnowledgeNode.metadata_['slug']`` values for the
  target course and hands them to the extractor as a ``slug_hint``,
* returns a :class:`ScreenshotCandidatesResponse` envelope with the
  cards, latency, and PII-drop count.

Nothing here writes screenshot bytes to disk or to the DB. Only the
16-char hash is retained (in-process cache key + later
``problem_metadata.screenshot_hash`` tag when T3 save-candidates
persists one of the returned candidates).

Plan reference: ``plan/screenshot_drill_phase4.md`` §T2.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any

from cachetools import TTLCache
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.knowledge_graph import KnowledgeNode
from models.user import User
from schemas.curriculum import CardCandidate
from schemas.screenshot import ScreenshotCandidatesResponse
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.screenshot.vision_extractor import extract_cards_from_image

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Tunables ────────────────────────────────────────────────

# Critic concern #2 — cap the screenshot body. gpt-4o-mini downscales to
# 768 px anyway, so the client should downsample to 1600 px long-side
# before POST (T4 does this in canvas); 5 MiB is generous headroom.
_MAX_IMAGE_BYTES: int = 5 * 1024 * 1024  # 5 MiB

# Only MIME types the OpenAI vision blocks accept natively. Anything
# else (PDF, HEIC, SVG, bitmap) is rejected with 415 so we never forward
# a payload the LLM cannot read.
_ALLOWED_MIMES: frozenset[str] = frozenset({"image/png", "image/jpeg", "image/webp"})

# Critic concern #4 — ADHD-spam protection. Token-bucket: user may
# burn 5 screenshots in 60 s, then gets 429s until the oldest timestamp
# falls out of the window.
_RATE_LIMIT_PER_MIN: int = 5
_RATE_LIMIT_WINDOW_SEC: float = 60.0

# Critic concern #5 — keyed on ``(user_id, screenshot_hash)`` so one
# user's cache hits don't leak into another's session. ``TTL=600``
# matches the plan ("same screenshot within 10 min → cache hit").
_CACHE_TTL_SEC: int = 600
_CACHE_MAXSIZE: int = 256


# ── Module-level state ──────────────────────────────────────

# Both singletons are deliberately in-process — per plan §Data model
# ("In-memory TTL cache, cachetools.TTLCache, keyed by (user_id,
# screenshot_hash), TTL=600s. Not Redis — per-process fine for personal
# tool.").
#
# Cache stores the already-serialised response fields so a hit can
# return bit-for-bit the same payload without rebuilding CardCandidate
# objects. Pydantic models are cheap to re-validate but this also
# immunises us against CardCandidate schema drift invalidating cache
# entries mid-process.
_RESULT_CACHE: TTLCache[tuple[str, str], dict[str, Any]] = TTLCache(
    maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SEC
)

# Token-bucket state — per-user deque of recent request timestamps.
# We prune expired entries on every request (see ``_check_rate_limit``).
_RATE_LIMIT_STATE: dict[str, deque[float]] = defaultdict(deque)


# ── Helpers ─────────────────────────────────────────────────


def _check_rate_limit(user_id: str) -> None:
    """Token-bucket check — raise HTTP 429 when a user exceeds the bucket.

    Evicts timestamps older than ``_RATE_LIMIT_WINDOW_SEC`` before
    counting so the bucket refills as the window slides forward. Uses
    ``time.monotonic`` so tests can monkeypatch a fake clock (see
    ``test_rate_limit_6th_in_60s_returns_429``).
    """

    now = time.monotonic()
    bucket = _RATE_LIMIT_STATE[user_id]

    # Evict expired entries from the left (oldest first).
    while bucket and bucket[0] <= now - _RATE_LIMIT_WINDOW_SEC:
        bucket.popleft()

    if len(bucket) >= _RATE_LIMIT_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail="Slow down — 5 screenshots per minute",
        )

    bucket.append(now)


async def _top_concept_slugs(
    db: AsyncSession, course_id: uuid.UUID, limit: int = 5
) -> list[str]:
    """Return up to ``limit`` concept slugs for the course.

    The slug lives in ``KnowledgeNode.metadata_['slug']`` (per §14.5
    T2). Nodes without a slug are ignored — this is a prompt hint, not
    an exhaustive inventory, so zero slugs is fine (extractor renders
    ``(none)`` in the prompt).

    Ordered by ``created_at`` ascending so the slug list is stable
    across retries of the same screenshot; `created_at ASC` matches the
    order in which the syllabus-builder seeded concepts, i.e. the most
    "foundational" slugs come first.
    """

    stmt = (
        select(KnowledgeNode.metadata_)
        .where(KnowledgeNode.course_id == course_id)
        .order_by(KnowledgeNode.created_at.asc())
    )
    rows = await db.execute(stmt)
    slugs: list[str] = []
    for (meta,) in rows.all():
        if not isinstance(meta, dict):
            continue
        slug = meta.get("slug")
        if isinstance(slug, str) and slug:
            slugs.append(slug)
            if len(slugs) >= limit:
                break
    return slugs


def _resolve_user_id(user: User) -> str:
    """Normalise the rate-limit / cache key across auth modes.

    ``get_current_user`` always returns a ``User`` row in both
    single-user and multi-user deployments, so ``user.id`` is never
    ``None``. Kept as a helper so the fallback behaviour (if a future
    auth refactor ever yields a stub user) is localised.
    """

    if user is None or user.id is None:
        return "default"
    return str(user.id)


def _serialise_candidates(cards: list[CardCandidate]) -> list[dict[str, Any]]:
    """Dump cards to primitive dicts for cache storage.

    ``model_dump`` — not ``model_dump_json`` — because the envelope
    response is assembled from these dicts via
    ``ScreenshotCandidatesResponse.model_validate`` on a cache hit.
    """

    return [c.model_dump() for c in cards]


# ── Route ───────────────────────────────────────────────────


@router.post(
    "/upload/screenshot",
    summary="Upload a screenshot for flashcard extraction",
    description=(
        "Accepts a PNG/JPEG/WebP image (≤5 MiB) plus ``course_id``, runs "
        "one vision-LLM call, and returns 0-5 flashcard candidates. "
        "Never stores bytes on disk; only ``sha256(bytes)[:16]`` is "
        "retained as a 10-minute idempotency tag."
    ),
    response_model=ScreenshotCandidatesResponse,
)
async def upload_screenshot(
    file: UploadFile = File(...),
    course_id: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScreenshotCandidatesResponse:
    """Vision-extract flashcard candidates from a screenshot upload."""

    # 1. MIME validate — reject before reading the body so a mis-labeled
    # 500 MiB PDF doesn't get slurped into memory.
    mime = (file.content_type or "").lower()
    if mime not in _ALLOWED_MIMES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported image type {mime!r}. "
                "Accepted: image/png, image/jpeg, image/webp."
            ),
        )

    # 2. Read bytes. ``file.read()`` is unbounded by default — we apply
    # the size cap immediately after.
    image_bytes = await file.read()

    # 3. Size cap.
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "detail": "Screenshot too large",
                "hint": ("Maximum 5 MiB; downsample client-side to 1600px long side"),
            },
        )
    if not image_bytes:
        # Empty uploads hit the LLM for nothing — reject early with 422
        # like the Coursera router does (mirror ``ValidationError``).
        raise HTTPException(status_code=422, detail="Empty upload")

    # 4. Hash — short 16-char sha256 prefix. Good enough for idempotency
    # inside a per-process TTL cache; collision risk is ~0 on personal
    # upload volumes.
    screenshot_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

    # 5. User resolve + 6. course_id parse.
    user_id = _resolve_user_id(user)
    try:
        cid = uuid.UUID(course_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid course_id") from exc

    # 404 when the course is missing or not owned — ownership check
    # matches ``upload_coursera`` exactly.
    await get_course_or_404(db, cid, user_id=user.id)

    # 7. Rate limit AFTER size / MIME / course validation so cheap-to-
    # detect client bugs don't burn through the user's bucket.
    _check_rate_limit(user_id)

    # 8. Cache lookup.
    cache_key = (user_id, screenshot_hash)
    cached = _RESULT_CACHE.get(cache_key)
    if cached is not None:
        logger.info(
            "screenshot_cache_hit user_id=%s hash=%s",
            user_id,
            screenshot_hash,
        )
        return ScreenshotCandidatesResponse.model_validate(
            {**cached, "vision_latency_ms": 0}
        )

    # 9. Fetch slug hint — best-effort. Failure here is NOT fatal; the
    # extractor renders an empty hint as "(none)" in the prompt.
    try:
        slug_hint = await _top_concept_slugs(db, cid, limit=5)
    except Exception:  # noqa: BLE001 — hint is a prompt nicety, not a guard
        logger.exception("screenshot_slug_hint_failed course_id=%s", cid)
        slug_hint = []

    # 10. Call T1 extractor. ``extract_cards_from_image`` never raises
    # per its contract — it always returns ``(cards, dropped_count)``.
    t0 = time.monotonic()
    cards, dropped = await extract_cards_from_image(
        image_bytes, mime, str(cid), slug_hint
    )
    vision_latency_ms = int((time.monotonic() - t0) * 1000)

    # Privacy log line — per plan §P1 AC #9, NEVER echo bytes/base64.
    logger.info(
        "screenshot_extracted user_id=%s hash=%s size=%d mime=%s "
        "cards=%d dropped=%d latency_ms=%d",
        user_id,
        screenshot_hash,
        len(image_bytes),
        mime,
        len(cards),
        dropped,
        vision_latency_ms,
    )

    # 11. Cache put — stable payload for cache hits.
    payload = {
        "candidates": _serialise_candidates(cards),
        "screenshot_hash": screenshot_hash,
        "vision_latency_ms": vision_latency_ms,
        "ungrounded_dropped_count": dropped,
    }
    _RESULT_CACHE[cache_key] = payload

    return ScreenshotCandidatesResponse.model_validate(payload)


# ── Internal reference for test monkeypatching ─────────────────
# Tests that want to assert "LLM called exactly once" monkeypatch
# ``extract_cards_from_image`` through *this* module's name-binding
# (not the service module's) so the patch covers the actual call site.
_extract_cards_from_image = extract_cards_from_image
