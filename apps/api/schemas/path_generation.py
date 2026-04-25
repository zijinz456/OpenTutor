"""Pydantic request/response schemas for the standard-room generation surface.

Phase 16b Bundle A — Subagent B scope (Parts A + D of the spec).

The router-side contract is intentionally split off from ``schemas/curriculum.py``
because the path-room factory has its own validation rules (topic guard,
3..120 length, prompt-injection deny-list) that should not bleed into the
existing curriculum/quiz domains.

Two response shapes for ``POST /api/paths/generate-room``:

* :class:`GenerateRoomAccepted` — 202 path. A real generation job was
  scheduled in the background and the client must subscribe to the SSE
  stream at ``GET /api/paths/generate-room/stream/{job_id}``.
* :class:`GenerateRoomReused` — 200 path. The factory found a recently-
  generated room with the same ``generation_seed`` and is handing it
  straight back. No SSE stream, no ``job_id``.

The router keeps the union loose (returns ``dict``) so FastAPI's response
serialiser doesn't fight Pydantic's discriminated-union machinery — the
schemas here exist for the clarity-of-intent of the contract and for
re-use by tests.
"""

from __future__ import annotations

import re
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Topic guard ─────────────────────────────────────────────────────


# Banned substrings (case-insensitive contains-check). These are
# intentionally narrow — we are not trying to be a general-purpose
# prompt-injection classifier here, we just want to refuse the obvious
# attacks before any LLM call:
#
#   * triple backticks → tries to break out of a fenced JSON-only prompt
#   * ``<system>`` / ``<assistant>`` → tries to inject a fake role tag
#   * ``ignore previous`` → the canonical jailbreak opener
#   * ``\nassistant:`` / ``\nuser:`` → tries to fake a chat boundary
#
# All checks operate on the *trimmed* input so leading whitespace can't
# slip a `\nassistant:` marker through.
_BANNED_SUBSTRINGS: tuple[str, ...] = (
    "```",
    "<system>",
    "<assistant>",
    "ignore previous",
    "\nassistant:",
    "\nuser:",
)


def validate_topic(text: str) -> str:
    """Normalise + screen a free-form topic string for prompt safety.

    Returns the stripped topic when accepted. Raises ``ValueError`` with
    a stable error code (caller maps to HTTP 400) on:

    * empty / whitespace-only input after trimming
    * length outside ``3..120`` after trimming
    * any of the six banned substrings present (case-insensitive)
    """

    if not isinstance(text, str):
        raise ValueError("topic_must_be_string")
    trimmed = text.strip()
    if len(trimmed) < 3:
        raise ValueError("topic_too_short")
    if len(trimmed) > 120:
        raise ValueError("topic_too_long")

    lower = trimmed.lower()
    for needle in _BANNED_SUBSTRINGS:
        if needle.lower() in lower:
            raise ValueError("topic_guard")
    # Also reject literal CR-prefixed variants that might survive
    # platform-specific newline rewriting before reaching us.
    if re.search(r"(?i)\r\n?(assistant|user)\s*:", trimmed):
        raise ValueError("topic_guard")

    return trimmed


# ── Request ─────────────────────────────────────────────────────────


class GenerateRoomRequest(BaseModel):
    """Validated body for ``POST /api/paths/generate-room``.

    ``model_config.extra = "forbid"`` keeps the contract honest: a client
    that sends a hacking-room field (``target_url``, ``lab_type``, etc.)
    gets rejected with a 422 before any DB query, instead of silently
    dropping the field and persisting an inconsistent room.
    """

    model_config = ConfigDict(extra="forbid")

    path_id: UUID
    course_id: UUID
    topic: str = Field(min_length=1, max_length=500)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    task_count: int = Field(ge=3, le=8)

    @field_validator("topic")
    @classmethod
    def _topic_must_pass_guard(cls, value: str) -> str:
        """Run the trim+length+deny-list check inside Pydantic.

        Pydantic will surface the ``ValueError`` as a 422 by default,
        but the router intercepts the request before the validator runs
        (via a manual parse) so it can return a 400 with a stable
        ``error: "topic_guard"`` code. The validator stays here as a
        belt-and-braces guard for any callsite that constructs the
        model directly (e.g. a test).
        """

        return validate_topic(value)


# ── Responses ───────────────────────────────────────────────────────


class GenerateRoomAccepted(BaseModel):
    """202 response — background job scheduled.

    The client subscribes to the SSE stream at
    ``GET /api/paths/generate-room/stream/{job_id}`` to follow progress.
    """

    job_id: str
    reused: Literal[False] = False


class GenerateRoomReused(BaseModel):
    """200 response — an existing generated room was reused.

    The ``job_id`` is intentionally ``None`` so a thin client can branch
    on ``reused`` without checking the existence of two separate fields.
    """

    job_id: Optional[str] = None
    reused: Literal[True] = True
    room_id: UUID
    path_id: UUID


class GenerateRoomError(BaseModel):
    """Stable error envelope for documented 4xx codes.

    Wrapped under ``detail`` to match FastAPI's ``HTTPException`` shape.
    """

    detail: dict


__all__ = [
    "GenerateRoomAccepted",
    "GenerateRoomError",
    "GenerateRoomRequest",
    "GenerateRoomReused",
    "validate_topic",
]
