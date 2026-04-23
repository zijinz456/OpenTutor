"""Vision extractor — one vision-LLM call per uploaded screenshot.

Part of MASTER §14 Phase 4 (Screenshot-to-Drill). The T2 router hands
this module the raw image bytes plus a shortlist of course-concept
slugs; we base64-encode the image, ask a vision-capable LLM for 3-5
flashcard candidates, post-filter PII, and hand the validated cards
back to the router for persistence via the existing save-candidates
path (T3).

Design notes
------------
* **No DB access.** The function is pure over
  ``(image_bytes, mime, course_id, slug_hint)``. Bytes are never written
  to disk — we compute a ``sha256[:16]`` tag at the router level for
  idempotency and then discard the buffer.
* **Total budget: 20 seconds wall-clock**, including any retry. Matches
  plan §Architecture ("soft-ship: vision call >20s logs warning but
  still returns"). Enforced by an ``asyncio.wait_for`` wrapper around
  the attempt loop. On ``TimeoutError`` we return ``([], 0)`` and log
  a warning — we never raise.
* **Retry-once ONLY on parse/validation failure.** Transport errors
  (network, rate limit, 5xx) do NOT retry — a second call would
  re-hit the same rate-limiter and compound latency. This is the
  plan §Architecture "retry only on JSON/pydantic errors" flag.
* **PII regex filter.** After the LLM validates, each card's ``front``
  and ``back`` is scanned for credential patterns (OpenAI/Groq/GitHub
  keys, Slack tokens, long base64 blocks, emails, literal
  "password: …" lines). Matching cards are dropped and counted; the
  counter surfaces as ``ungrounded_dropped_count`` in the T2 response.
* **Never raises.** Every failure mode — transport, timeout, JSON
  parse, pydantic validation, PII filter nuking everything — results
  in a clean ``([], dropped_count)`` return with an appropriate log
  line. The caller (T2 router) can treat the result as "zero or more
  candidates" without a try/except.

Plan reference: ``plan/screenshot_drill_phase4.md`` §LLM contract +
§Critic concern #1 (privacy PII strip).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re

from pydantic import ValidationError

from schemas.curriculum import CardCandidate
from schemas.screenshot import CardBatchWide
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────

# Total wall-clock budget for the whole ``extract_cards_from_image``
# call, including the retry. Plan constraint: ≤20s (soft-ship threshold
# where a warning is logged but the call still completes).
_TIMEOUT_SEC: float = 20.0

# Retry budget on parse/validation failure. One retry = two total
# attempts. Transport errors do NOT consume retries — they bail out
# immediately (see ``_call_llm_once`` error classification).
_MAX_ATTEMPTS: int = 2

# Hard cap on returned cards, independent of schema. Defensive against
# schema drift — if ``CardBatchWide.cards`` ever relaxes, we still
# honour the contract.
_MAX_CARDS: int = 5


SCREENSHOT_SYSTEM_PROMPT = """\
You are a spaced-repetition card extractor with vision. You are given a
single screenshot the learner captured while working. Produce 3 to 5
short recall-worthy question/answer pairs grounded ONLY in what is
visible in the image. Output ONLY a JSON object matching this schema:
{"cards": [{"front": "...", "back": "...", "concept_slug": "..."}, ...]}

Hard rules:
- 3 to 5 cards. Zero is wrong — if the screenshot is too empty for 3
  cards, still return your 3 best questions rather than refusing.
- Use ONLY facts visible in the image. No external knowledge, no
  extrapolation, no code you "assume" is there.
- Each "front" is a single standalone question (<=200 chars).
- Each "back" is <=500 chars, sourced from the image.
- "concept_slug" is optional kebab-case; prefer one of the provided
  hints when the card genuinely matches that concept.
- If the image contains credentials, API keys, tokens, passwords,
  private email addresses, or identifiable personal data — output
  {"cards": []} and skip extraction. Do not echo those values into the
  cards.

Style: prefer "why does X fail?" / "what does Y return?" / "what's the
role of Z?" over trivia like "what's the line number?".\
"""


SCREENSHOT_USER_PROMPT = """\
Extract 3-5 flashcards from the attached screenshot.
Available course concepts (prefer one if it genuinely matches): {slug_hint}
Return ONLY the JSON object, no prose.\
"""


# ── PII regex filter ────────────────────────────────────────
#
# Belt-and-suspenders defense against the vision LLM either:
#   (a) ignoring the "refuse on credentials" system-prompt clause, or
#   (b) paraphrasing a visible secret into a card even when it "knows"
#       it was a secret.
#
# Patterns are deliberately overbroad — the plan flag #3 resolution
# ("accept false-positives on long hashes") means a noisy match is
# preferable to a leaked key. A card dropped by this filter is cheap;
# a leaked key persisted to FSRS is not.

_PII_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # OpenAI-style keys
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),  # Groq keys
    re.compile(r"ghp_[A-Za-z0-9]{20,}"),  # GitHub PATs
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),  # Slack tokens
    re.compile(r"[A-Za-z0-9+/]{32,}={0,2}"),  # long base64 blocks
    re.compile(r"[\w\.\-]+@[\w\-]+\.[\w\-\.]+"),  # email addresses
    re.compile(r"(?i)password\s*[:=]\s*\S+"),  # literal password line
)


def _contains_pii(text: str) -> bool:
    """Return True if ``text`` matches any credential/PII pattern.

    A single positive match is enough to drop the enclosing card — we
    don't try to surgically redact because a vision LLM's paraphrase
    may have already split the secret across words.
    """

    return any(p.search(text) for p in _PII_PATTERNS)


# ── Helpers ─────────────────────────────────────────────────


def _extract_json_object(raw: str) -> str | None:
    """Carve a JSON object out of an LLM response.

    Same trick as ``card_spawner``/``syllabus_builder``: LLMs wrap
    structured output in markdown fences or trailing prose despite
    instructions. We grab the span from the first ``{`` to the last
    ``}`` — ``json.loads`` on the result is still the source of truth.
    """

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    return raw[start : end + 1]


def _build_user_prompt(slug_hint: list[str] | None) -> str:
    """Render the user prompt with the course slug shortlist.

    ``slug_hint`` is a metadata hint ONLY — the LLM is instructed to
    source facts from the image, not from this list. Empty/missing
    hints render as ``"(none)"`` so the prompt stays unambiguous.
    """

    if slug_hint:
        hint_str = ", ".join(slug_hint)
    else:
        hint_str = "(none)"
    return SCREENSHOT_USER_PROMPT.format(slug_hint=hint_str)


class _TransportFailure(Exception):
    """Internal signal: the LLM call failed at transport level (network
    error, rate limit, client-init failure, or any unexpected
    exception). Caught by :func:`_attempt_loop` which bails out
    immediately rather than spending a retry slot on a sticky failure.
    """


async def _call_llm_once(
    system_prompt: str,
    user_prompt: str,
    image_payload: list[dict[str, str]],
) -> str:
    """One vision round-trip. Returns raw text on success; raises
    :class:`_TransportFailure` on ANY other outcome.

    We deliberately collapse every non-success path to a single
    exception class because the retry policy is binary — transport
    failures never retry, parse failures always retry once. The caller
    distinguishes the two by catching this exception vs. by checking
    for ``None`` from :func:`_parse_batch`.

    Routes to the ``frontier`` variant (gpt-4o-mini by default —
    vision-capable) and passes the image via the existing
    ``images=[...]`` kwarg on :class:`OpenAIClient.chat`.
    """

    try:
        client = get_llm_client("frontier")
    except (ImportError, RuntimeError) as exc:
        logger.exception("vision_extractor: LLM client unavailable (%s)", exc)
        raise _TransportFailure(str(exc)) from exc

    try:
        raw, _ = await client.chat(
            system_prompt,
            user_prompt,
            images=image_payload,
        )
    except Exception as exc:
        # Catch-all: transport errors, rate limits, unexpected provider
        # exceptions — all non-retryable in our policy. ``exception``
        # (not ``warning``) so the traceback is captured for debugging.
        logger.exception("vision_extractor: LLM call failed (%s)", exc)
        raise _TransportFailure(str(exc)) from exc
    return raw


def _parse_batch(raw: str) -> CardBatchWide | None:
    """JSON-decode + pydantic-validate a vision LLM response.

    ``None`` on any failure — caller treats that as a signal to spend
    its one retry slot. Transport errors are handled separately in
    ``_call_llm_once`` (they return ``None`` too but via a different
    path).
    """

    payload = _extract_json_object(raw)
    if payload is None:
        logger.debug("vision_extractor: no JSON object found in response")
        return None

    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.debug("vision_extractor: JSON decode failed: %s", exc)
        return None

    try:
        return CardBatchWide.model_validate(obj)
    except ValidationError as exc:
        logger.debug("vision_extractor: pydantic validation failed: %s", exc)
        return None


def _apply_pii_filter(
    cards: list[CardCandidate],
    course_id: str,
) -> tuple[list[CardCandidate], int]:
    """Drop cards whose ``front`` or ``back`` matches any PII pattern.

    Returns ``(kept, dropped_count)``. Each drop is logged at WARNING
    with a deliberately minimal ``extra`` payload — we record THAT a
    pattern matched and the course, never the matching text itself
    (the whole point of the filter is to avoid echoing secrets into
    the log stream).
    """

    kept: list[CardCandidate] = []
    dropped = 0
    for card in cards:
        if _contains_pii(card.front) or _contains_pii(card.back):
            dropped += 1
            logger.warning(
                "screenshot_pii_dropped",
                extra={"pattern_matched": True, "course_id": course_id},
            )
            continue
        kept.append(card)
    return kept, dropped


async def _attempt_loop(
    system_prompt: str,
    user_prompt: str,
    image_payload: list[dict[str, str]],
    course_id: str,
) -> tuple[list[CardCandidate], int]:
    """Run up to ``_MAX_ATTEMPTS`` attempts. Returns the PII-filtered
    card list on first parse success.

    Retry policy (plan §T1 item 10):
    * Transport/network error (``raw is None`` from ``_call_llm_once``)
      → bail out immediately, return ``([], 0)``. Re-hitting the
      provider is pointless — rate-limits and 5xx are sticky on the
      sub-20s scale and compound latency.
    * JSON / pydantic failure (``batch is None`` from ``_parse_batch``)
      → consume one retry slot and try again.
    """

    for attempt in range(_MAX_ATTEMPTS):
        try:
            raw = await _call_llm_once(system_prompt, user_prompt, image_payload)
        except _TransportFailure:
            # Transport-level failure — retrying would re-hit the same
            # rate-limiter. Return empty rather than burning the budget.
            # The original ``logger.exception`` already fired inside
            # ``_call_llm_once``; no need to double-log.
            logger.warning(
                "vision_extractor: transport failure on attempt %d, "
                "abandoning (no retry on transport errors)",
                attempt + 1,
            )
            return [], 0

        batch = _parse_batch(raw)
        if batch is not None:
            capped = batch.cards[:_MAX_CARDS]
            kept, dropped = _apply_pii_filter(capped, course_id)
            logger.info(
                "vision_extractor: attempt %d yielded %d card(s) "
                "(%d dropped by PII filter)",
                attempt + 1,
                len(kept),
                dropped,
            )
            return kept, dropped

        logger.debug(
            "vision_extractor: attempt %d/%d failed parse/validation",
            attempt + 1,
            _MAX_ATTEMPTS,
        )

    logger.warning(
        "vision_extractor: all %d attempts failed parsing, returning []",
        _MAX_ATTEMPTS,
    )
    return [], 0


# ── Public API ──────────────────────────────────────────────


async def extract_cards_from_image(
    image_bytes: bytes,
    mime: str,
    course_id: str,
    slug_hint: list[str] | None = None,
) -> tuple[list[CardCandidate], int]:
    """Extract 3-5 flashcards from a screenshot via vision LLM.

    Entirely stateless — no DB access, no disk writes, no telemetry
    beyond the structured log lines. The T2 router is responsible for
    hashing, caching, and persisting results.

    Budget: ≤20s wall-clock including one retry. Every failure mode
    (transport error, timeout, JSON parse, pydantic validation, PII
    filter nuking everything) yields ``([], dropped_count)`` — this
    function never raises.

    Args:
        image_bytes: Raw screenshot bytes as uploaded. Never written
            to disk; base64-encoded in-memory for the vision prompt
            and then discarded.
        mime: MIME type of the image, one of ``image/png``,
            ``image/jpeg``, ``image/webp``. Passed through to the
            OpenAI-compatible vision content block as the
            ``media_type`` field. Validation that the bytes actually
            match is T2's job; this function trusts the label.
        course_id: Course the screenshot is being saved into. Used
            purely for log correlation (``screenshot_pii_dropped``
            log records embed it) — never sent to the LLM.
        slug_hint: Optional shortlist of course concept slugs (top-5
            is the plan recommendation) the LLM should prefer when
            tagging cards. Rendered into the user prompt as a
            comma-separated list; empty / ``None`` becomes ``"(none)"``.

        Returns:
            ``(cards_kept, ungrounded_dropped_count)`` — a list of 0 to
            5 :class:`CardCandidate` items plus the count of cards the
            PII filter removed. Empty list is a legitimate result
            (all cards filtered, or all attempts exhausted).
    """

    # Base64-encode inline. ``bytes -> str`` via ASCII is safe because
    # the base64 alphabet is a strict subset of ASCII.
    try:
        base64_data = base64.b64encode(image_bytes).decode("ascii")
    except (TypeError, ValueError) as exc:
        # Defensive: ``b64encode`` on ``bytes`` cannot realistically
        # fail, but we keep the exception handler so any future change
        # to the input type still honours the never-raises contract.
        logger.exception("vision_extractor: base64 encode failed: %s", exc)
        return [], 0

    image_payload: list[dict[str, str]] = [{"media_type": mime, "data": base64_data}]
    user_prompt = _build_user_prompt(slug_hint)

    try:
        return await asyncio.wait_for(
            _attempt_loop(
                SCREENSHOT_SYSTEM_PROMPT,
                user_prompt,
                image_payload,
                course_id,
            ),
            timeout=_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "vision_extractor: timed out after %.1fs budget, returning []",
            _TIMEOUT_SEC,
        )
        return [], 0
    except Exception:
        # Catch-all to honour the never-raises contract. Anything that
        # escapes ``_attempt_loop`` (e.g. an unexpected AttributeError
        # from a future LLM client refactor) becomes a warning log and
        # an empty list rather than a 500 up the call stack.
        logger.exception("vision_extractor: unexpected failure, returning []")
        return [], 0


__all__ = [
    "SCREENSHOT_SYSTEM_PROMPT",
    "SCREENSHOT_USER_PROMPT",
    "extract_cards_from_image",
]
