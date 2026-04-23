"""Voice-to-text upload endpoint (Phase 8 T2).

Thin HTTP wrapper around ``services.voice.whisper_client.transcribe_audio``:

* validates the uploaded audio (MIME whitelist + <=10 MiB size cap),
* user-scoped token-bucket rate limit (10 req/min),
* user-scoped TTL cache keyed on ``sha256(bytes)[:16]`` so replaying the
  same clip within 10 minutes is free (zero Whisper calls),
* returns a :class:`TranscribeResponse` envelope with the text,
  detected language, and audio duration.

Audio bytes are NEVER persisted to disk or to the DB here. Only the
16-char hash survives (as a per-process cache key). The whisper client
itself also refuses to log transcript text — see the module docstring
there.

Pattern mirrors ``apps/api/routers/upload_screenshot.py`` (5/min screenshot
bucket) — only the limits, MIME whitelist, and downstream call differ.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict, deque
from typing import Any

from cachetools import TTLCache
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from models.user import User
from schemas.voice import TranscribeResponse
from services.auth.dependency import get_current_user
from services.voice.whisper_client import transcribe_audio

logger = logging.getLogger(__name__)

router = APIRouter()


# -- Tunables -----------------------------------------------------------

# Whisper-1 accepts up to 25 MiB. We cap at 10 MiB — one minute of 128 kbps
# opus fits in ~1 MiB, so 10 MiB is already ~10 min of speech. Anything
# larger is almost certainly an accidental upload of the wrong file.
_MAX_AUDIO_BYTES: int = 10 * 1024 * 1024  # 10 MiB

# MIME whitelist — MediaRecorder in Chrome/Safari emits webm/ogg/mp4,
# iOS Safari emits m4a. audio/wav covers desktop recorders. Anything not
# in this set is rejected with 415 so we don't forward payloads Whisper
# cannot decode (MP3 works in practice but the frontend doesn't produce
# it — keep the whitelist tight, per plan AC #2).
_ALLOWED_MIMES: frozenset[str] = frozenset(
    {
        "audio/webm",
        "audio/mp4",
        "audio/wav",
        "audio/ogg",
        "audio/x-m4a",
    }
)

# Token-bucket: 10 voice transcriptions per minute per user (plan AC #4).
# Higher than the screenshot bucket (5/min) because voice clips are cheap
# compared to vision calls and the UX encourages short "think-aloud"
# bursts.
_RATE_LIMIT_PER_MIN: int = 10
_RATE_LIMIT_WINDOW_SEC: float = 60.0

# Idempotency cache — same clip replayed within 10 min returns the stored
# response without another Whisper call. Keyed by ``(user_id, hash)`` so
# users don't see each other's results.
_CACHE_TTL_SEC: int = 600
_CACHE_MAXSIZE: int = 128


# -- Module-level state -------------------------------------------------

# Cache stores the already-serialised response dict so a hit re-builds a
# ``TranscribeResponse`` via ``model_validate`` without re-running any
# transcription logic. In-process per plan ("not Redis — per-process is
# fine for personal tool").
_RESULT_CACHE: TTLCache[tuple[str, str], dict[str, Any]] = TTLCache(
    maxsize=_CACHE_MAXSIZE, ttl=_CACHE_TTL_SEC
)

# Token-bucket: per-user deque of recent request timestamps (monotonic).
# Expired entries pruned on each request in ``_check_rate_limit``.
_RATE_LIMIT_STATE: dict[str, deque[float]] = defaultdict(deque)


# -- Helpers ------------------------------------------------------------


def _check_rate_limit(user_id: str) -> None:
    """Token-bucket check — raise HTTP 429 if the user over-fires.

    Uses ``time.monotonic`` so tests can monkeypatch a fake clock. Evicts
    expired timestamps from the left before counting so the bucket slides
    forward as the window advances.
    """

    now = time.monotonic()
    bucket = _RATE_LIMIT_STATE[user_id]

    while bucket and bucket[0] <= now - _RATE_LIMIT_WINDOW_SEC:
        bucket.popleft()

    if len(bucket) >= _RATE_LIMIT_PER_MIN:
        raise HTTPException(
            status_code=429,
            detail="Slow down — 10 voice transcriptions per minute",
        )

    bucket.append(now)


def _resolve_user_id(user: User) -> str:
    """Normalise the rate-limit / cache key across auth modes.

    Mirrors ``upload_screenshot._resolve_user_id`` — in single-user mode
    ``user.id`` is always populated, but the defensive fallback keeps the
    router robust against a future auth refactor that yields a stub user.
    """

    if user is None or user.id is None:
        return "default"
    return str(user.id)


# -- Route --------------------------------------------------------------


@router.post(
    "/transcribe",
    summary="Transcribe an audio clip via Whisper",
    description=(
        "Accepts a webm/ogg/mp4/m4a/wav audio clip (<=10 MiB) plus an "
        "optional BCP-47 language hint (en / uk). Runs one Whisper call "
        "and returns the transcript, detected language, and clip duration. "
        "Never persists bytes to disk; only ``sha256(bytes)[:16]`` is "
        "retained as a 10-minute idempotency tag."
    ),
    response_model=TranscribeResponse,
)
async def transcribe(
    file: UploadFile = File(...),
    language: str | None = Form(None),
    user: User = Depends(get_current_user),
) -> TranscribeResponse:
    """Transcribe an audio upload via OpenAI Whisper."""

    # 1. MIME whitelist — reject before reading the body so a mis-labeled
    # giant blob never gets slurped into memory.
    mime = (file.content_type or "").lower()
    if mime not in _ALLOWED_MIMES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported audio type {mime!r}. "
                "Accepted: audio/webm, audio/mp4, audio/wav, audio/ogg, audio/x-m4a."
            ),
        )

    # 2. Read bytes + size cap. UploadFile.read() is unbounded; the cap
    # applies immediately after.
    audio_bytes = await file.read()
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "detail": "Audio too large",
                "hint": (
                    "Maximum 10 MiB; record a shorter clip or re-encode "
                    "at a lower bitrate"
                ),
            },
        )
    if not audio_bytes:
        # Empty uploads would burn a Whisper call for nothing — reject early.
        raise HTTPException(status_code=422, detail="Empty upload")

    # 3. Hash — short 16-char sha256 prefix. Collision risk is ~0 at the
    # personal-tool volume this endpoint serves.
    audio_hash = hashlib.sha256(audio_bytes).hexdigest()[:16]

    user_id = _resolve_user_id(user)

    # 4. Rate limit. Runs BEFORE the cache lookup so a burst of identical
    # replays still counts against the bucket — otherwise a loop posting
    # the same clip would bypass the limiter entirely.
    _check_rate_limit(user_id)

    # 5. Cache lookup.
    cache_key = (user_id, audio_hash)
    cached = _RESULT_CACHE.get(cache_key)
    if cached is not None:
        logger.info(
            "voice_cache_hit user_id=%s hash=%s",
            user_id,
            audio_hash,
        )
        return TranscribeResponse.model_validate(cached)

    # 6. Call T1 Whisper client. Never raises — always returns a dict
    # with ``text``, ``language``, ``duration_ms``, ``error``.
    result = await transcribe_audio(
        audio_bytes,
        content_type=mime,
        language_hint=language,
    )

    # 7. Error map — whisper_client folds every SDK exception into
    # ``error``. Surface that as a 502 so the frontend can show an
    # ADHD-friendly hint and keep the textarea as the source of truth.
    if result.get("error"):
        logger.warning(
            "voice_transcribe_failed user_id=%s hash=%s error=%s",
            user_id,
            audio_hash,
            result["error"],
        )
        raise HTTPException(
            status_code=502,
            detail={
                "detail": "Transcription failed",
                "hint": "Try again",
            },
        )

    # Privacy log line — per plan AC #9, NEVER echo audio bytes or the
    # transcribed text. Only hash, duration, and detected language.
    logger.info(
        "voice_transcribed user_id=%s hash=%s size=%d mime=%s "
        "language=%s duration_ms=%s",
        user_id,
        audio_hash,
        len(audio_bytes),
        mime,
        result.get("language"),
        result.get("duration_ms"),
    )

    # 8. Cache put — store just the TranscribeResponse-shaped fields so
    # a hit re-validates into the same envelope.
    payload = {
        "text": result.get("text", ""),
        "language": result.get("language"),
        "duration_ms": result.get("duration_ms"),
        "error": None,
    }
    _RESULT_CACHE[cache_key] = payload

    return TranscribeResponse.model_validate(payload)


# -- Internal reference for test monkeypatching -------------------------
# Tests monkeypatch ``transcribe_audio`` through this module's name-
# binding (not the service module's) so the patch covers the actual
# call site — same pattern as ``upload_screenshot._extract_cards_from_image``.
_transcribe_audio = transcribe_audio
