"""Pydantic schemas for the Screenshot-to-Drill feature (Phase 4).

Two LLM/API contracts live here:

1. ``CardBatchWide`` — produced by ``services.screenshot.vision_extractor``.
   One vision-LLM call per uploaded screenshot. Emits 3 to 5
   :class:`~schemas.curriculum.CardCandidate` entries grounded in the
   image (wider range than ``CardBatch``'s 1-3 because a screenshot
   typically contains denser recall-worthy material than a single chat
   turn).

2. ``ScreenshotCandidatesResponse`` — HTTP response body for T2's
   ``POST /upload/screenshot`` router. Envelopes the extractor output
   plus idempotency and telemetry fields the frontend needs.

The schema-level difference between ``CardBatch`` and ``CardBatchWide``
is only the card-count cap (3 vs 5); both reuse the same
``CardCandidate`` element type, so the save-candidates endpoint (T3)
can consume either source without a branch.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from schemas.curriculum import CardCandidate


# ── vision_extractor — one call per screenshot upload ────────


class CardBatchWide(BaseModel):
    """Vision-extracted batch — 3 to 5 cards (wider than chat-turn 1-3).

    Lower bound is ``0`` rather than ``3`` because the extractor drops
    cards containing PII (keys/tokens/emails/passwords) after the LLM
    returns. A screenshot full of credentials will legitimately yield
    ``cards=[]`` post-filter, and that must validate successfully —
    otherwise the filter's only escape hatch would be raising.
    """

    cards: list[CardCandidate] = Field(min_length=0, max_length=5)


# ── POST /upload/screenshot response envelope (T2) ───────────


class ScreenshotCandidatesResponse(BaseModel):
    """Response body for ``POST /upload/screenshot``.

    Fields:
        candidates: 0 to 5 flashcard candidates. Empty list is a valid
            response — it means the extractor ran but returned nothing
            salvageable (all cards failed PII filter, or vision call
            exhausted retries). The frontend shows a muted toast in
            that case rather than an error.
        screenshot_hash: ``sha256(image_bytes)[:16]`` — stable
            idempotency tag. Re-uploading the same bytes within the
            10-minute TTL cache window returns the cached candidates
            with the same hash and zero LLM cost. Also persisted in
            ``practice_problems.problem_metadata.screenshot_hash`` on
            save for audit.
        vision_latency_ms: Wall-clock time spent inside the vision LLM
            call, not including validation or hashing. Surfaced to the
            frontend for P95 telemetry and to the MASTER §27 dashboards.
        ungrounded_dropped_count: Number of cards the LLM returned that
            were removed by the PII regex filter before this response
            was built. Defaults to ``0`` when nothing was dropped.
            Useful for the T6 warning banner ("1 card dropped —
            detected credential pattern").
    """

    candidates: list[CardCandidate]
    screenshot_hash: str
    vision_latency_ms: int
    ungrounded_dropped_count: int = 0


__all__ = ["CardBatchWide", "ScreenshotCandidatesResponse"]
