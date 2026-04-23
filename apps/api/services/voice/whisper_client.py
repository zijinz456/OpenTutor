"""OpenAI Whisper speech-to-text client.

Phase 8 (voice_whisper_phase8.md) T1. A thin, isolated wrapper around
``AsyncOpenAI.audio.transcriptions.create(model="whisper-1", ...)``.

Design rules (critic-absorbed):
    * Audio bytes are NEVER written to disk by this module. The caller
      passes a bytes buffer, we hand it to the SDK, and nothing is
      retained here.
    * Log lines EXCLUDE both the audio bytes AND the transcribed text.
      Only duration, detected language, and a short audio-hash tag are
      safe to emit (and those are the caller's responsibility — this
      module does not log).
    * Never raises on OpenAI API errors. Returns a structured dict with
      an ``error`` field so the router can map to an ADHD-friendly hint
      without a try/except ladder at every call-site.
    * Language post-processing normalises Whisper's verbose-json
      ``language`` field (``"english"`` / ``"ukrainian"``) to ISO 639-1
      codes (``"en"`` / ``"uk"``).

Not in scope here: rate limiting, TTL-cache, MIME validation, size cap,
duration cap. Those live in the router (T2).
"""

from __future__ import annotations

from io import BytesIO
from typing import Final

from openai import AsyncOpenAI

from config import settings

# Whisper returns the language as an English word in verbose_json
# (``"english"``, ``"ukrainian"``) rather than an ISO code. Normalise the
# two languages we actively support; pass anything else through as-is
# so the caller sees the raw Whisper label for unexpected detections
# (DE / PL / RU etc.). Keys are lower-cased on lookup.
_LANGUAGE_ISO_MAP: Final[dict[str, str]] = {
    "english": "en",
    "ukrainian": "uk",
}

# MIME → extension fallback for the SDK's ``file=(name, data, mime)``
# tuple. OpenAI uses the filename extension as a codec hint when the
# raw bytes lack a recognisable header (common with MediaRecorder webm
# fragments), so passing a sensible extension matters.
_MIME_EXT_MAP: Final[dict[str, str]] = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}


class WhisperError(Exception):
    """Structured error for Whisper API failures.

    Raised nowhere inside ``transcribe_audio`` (that function swallows
    exceptions into a dict). Kept as a public class so routers or
    higher-level orchestration code can construct / re-raise when they
    want exception-flow rather than dict-flow.

    Attributes:
        reason: Short, user-safe failure label (``"api_down"``,
            ``"invalid_audio"``, ...).
        hint: Optional ADHD-friendly recovery hint surfaced to the UI.
    """

    def __init__(self, reason: str, hint: str = ""):
        self.reason = reason
        self.hint = hint
        super().__init__(reason)


def _extension_for(content_type: str) -> str:
    """Pick a filename extension hint for the Whisper upload tuple."""
    return _MIME_EXT_MAP.get(content_type.lower(), "webm")


def _normalise_language(raw: str | None) -> str | None:
    """Map Whisper's verbose-json language label to ISO 639-1."""
    if not raw:
        return None
    return _LANGUAGE_ISO_MAP.get(raw.lower(), raw)


async def transcribe_audio(
    audio_bytes: bytes,
    content_type: str,
    language_hint: str | None = None,
) -> dict:
    """Transcribe ``audio_bytes`` via the OpenAI Whisper API.

    Args:
        audio_bytes: Raw audio payload. Not inspected or persisted here.
        content_type: MIME type of the payload, e.g. ``"audio/webm"``.
            Used only to derive the filename-extension hint handed to
            the SDK.
        language_hint: Optional BCP-47 language code. ``None`` lets
            Whisper auto-detect from the waveform. Pass ``"en"`` /
            ``"uk"`` to force — best when the user explicitly toggled
            the EN/UA pill.

    Returns:
        A dict with keys ``text``, ``language``, ``duration_ms``, and
        ``error``. On success ``error`` is ``None``. On failure
        ``text`` is an empty string, ``language`` and ``duration_ms``
        are ``None``, and ``error`` carries a short reason string
        suitable for the router to map to an ADHD-friendly hint.

    Never raises on API errors — exceptions from the SDK are caught and
    folded into the ``error`` field. The router decides whether to emit
    a 5xx or fall back to "type instead" UX.
    """

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    filename = f"voice.{_extension_for(content_type)}"

    create_kwargs: dict = {
        "model": "whisper-1",
        "file": (filename, BytesIO(audio_bytes), content_type),
        # verbose_json is the only response_format that returns both
        # the detected language and the audio duration in one call —
        # we need both for the VoiceTranscribeResponse envelope.
        "response_format": "verbose_json",
        # temperature=0 keeps Whisper deterministic. The model
        # sometimes "creatively rewrites" short clips at higher T,
        # which is the opposite of what a dictation UI wants.
        "temperature": 0,
    }
    if language_hint:
        create_kwargs["language"] = language_hint

    try:
        resp = await client.audio.transcriptions.create(**create_kwargs)
    except Exception as exc:  # noqa: BLE001 — see module docstring.
        # We deliberately swallow every SDK exception into a structured
        # dict. The router needs a single shape to reason about; each
        # branching exception type (APIConnectionError, RateLimitError,
        # 4xx APIError, ...) becomes noise at that layer. The string is
        # safe to log — it never contains audio bytes or transcript
        # text (OpenAI SDK errors carry status + message only).
        return {
            "text": "",
            "language": None,
            "duration_ms": None,
            "error": str(exc),
        }

    # Verbose-json responses expose ``.text``, ``.language``, ``.duration``
    # (float seconds). Missing attrs fall back to safe defaults rather
    # than raising — a future SDK shape change should degrade gracefully.
    text = getattr(resp, "text", "") or ""
    language = _normalise_language(getattr(resp, "language", None))
    duration_s = getattr(resp, "duration", None)
    duration_ms = int(round(duration_s * 1000)) if duration_s is not None else None

    return {
        "text": text,
        "language": language,
        "duration_ms": duration_ms,
        "error": None,
    }


__all__ = ["WhisperError", "transcribe_audio"]
