"""Pydantic schemas for the Voice (Whisper STT) feature — Phase 8.

Two HTTP contracts live here:

1. ``TranscribeResponse`` — body of ``POST /api/voice/transcribe``.
   Mirrors ``services.voice.whisper_client.transcribe_audio``'s return
   dict so the router layer is a thin envelope + rate-limit + cache
   pass-through, not a translation layer.

2. ``VoiceRateLimitMeta`` — optional header-ish metadata the router
   can surface so the frontend shows a "6 clips remaining this minute"
   pill without a second round-trip.
"""

from __future__ import annotations

from pydantic import BaseModel


class TranscribeResponse(BaseModel):
    """Response body for ``POST /api/voice/transcribe``.

    On success ``error`` is ``None`` and the other fields carry the
    Whisper output. On failure ``text`` is ``""``, ``language`` and
    ``duration_ms`` are ``None``, and ``error`` is a short reason
    string the router maps to an ADHD-friendly copy (see P1 AC #9 in
    the phase-8 plan).

    The success / failure discrimination is intentionally a nullable
    ``error`` field rather than HTTP status codes: voice failures are
    never fatal (textarea remains the source of truth), so the 2xx +
    ``error=…`` shape lets the frontend render an inline hint without
    triggering global error-boundary logic.
    """

    text: str
    language: str | None = None
    duration_ms: int | None = None
    error: str | None = None


class VoiceRateLimitMeta(BaseModel):
    """Per-user voice rate-limit state surfaced to the UI.

    Defaults mirror the router's token bucket: 10 requests per 60 s
    window (see ``plan/voice_whisper_phase8.md`` P0 AC #4).
    """

    requests_remaining: int
    window_seconds: int = 60


__all__ = ["TranscribeResponse", "VoiceRateLimitMeta"]
