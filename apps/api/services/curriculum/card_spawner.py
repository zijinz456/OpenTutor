"""Card spawner — one LLM call per tutor chat turn → up to 3 flashcard candidates.

Part of §14.5 v2.1 (URL → auto-curriculum). After each tutor response is
streamed to the learner, the orchestrator (T5) fires this service in the
background to extract short recall-worthy question/answer pairs grounded
in the response text. The resulting candidates are cached and surfaced to
the frontend as a "Save N cards?" toast; the save path (T6) is what
actually writes them to ``practice_problems`` + FSRS.

Design notes
------------
* **No DB access.** The function is pure over ``(response_text, chunk_ids,
  course_id)``. ``chunk_ids`` and ``course_id`` are passed in as metadata
  hints for the prompt (e.g. "focus on terminology core to this course")
  but we never query them. T4 is orthogonal to persistence — that is T6.
* **Total budget: 8 seconds wall-clock**, including any retry. Enforced by
  an ``asyncio.wait_for`` wrapper around the entire attempt loop. On
  ``TimeoutError`` we return ``[]`` and log a warning — we never raise.
* **Trivial-response short-circuit.** If the response is empty/whitespace
  or shorter than 100 chars of substantive text, skip the LLM entirely
  and return ``[]``. Saves a provider call on acknowledgments
  ("ok", "thanks", "I don't know").
* **Max 3 cards.** Enforced at both the schema level (``CardBatch.cards =
  Field(max_length=3)``) and defensively at the return boundary
  (``batch.cards[:3]``). Belt and suspenders; if a future schema change
  relaxes the schema cap this module still honours the contract.
* **Retry once** on parse/validation failure, same pattern as T1
  ``syllabus_builder``. Transport/network errors inside ``_call_llm_once``
  are swallowed and returned as ``None``, which also counts toward the
  attempt budget.
* **Never raises.** Every failure mode — transport, timeout, validation,
  trivial input — results in a clean ``[]`` return with an appropriate
  log line. The caller (orchestrator middleware) can treat the result as
  "zero or more candidates" without a try/except.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from pydantic import ValidationError

from schemas.curriculum import CardBatch, CardCandidate
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────

# Total wall-clock budget for the entire ``extract_card_candidates`` call,
# including both attempts. Critic/plan constraint: ≤8s.
_TIMEOUT_SEC: float = 8.0

# Retry budget on parse/validation failure. One retry = two total attempts.
_MAX_ATTEMPTS: int = 2

# Hard cap on returned cards, independent of schema. Defensive against
# schema drift — if ``CardBatch.cards`` is ever relaxed, we still cap at 3.
_MAX_CARDS: int = 3

# Minimum stripped length of ``response_text`` for us to bother calling
# the LLM. Responses shorter than this are overwhelmingly acknowledgments,
# refusals, or "I don't know" patterns that yield no recall-worthy
# material. Picked at 100 chars per plan guidance.
_TRIVIAL_RESPONSE_MIN_CHARS: int = 100

# Truncate very long responses before they become the prompt body — keeps
# us well under provider token caps and reduces "invent from unrelated
# tangent" risk. 8000 chars ≈ ~2k tokens, plenty for 3 cards worth of
# recall material.
_RESPONSE_CHAR_CAP: int = 8000


_SYSTEM_PROMPT = (
    "You are a spaced-repetition card extractor. You read a tutor's reply "
    "to a learner and produce 0 to 3 short recall-worthy question/answer "
    "pairs. Output ONLY valid JSON that matches the schema in the user "
    "message — no prose, no markdown fences, no explanation."
)

_USER_PROMPT_TEMPLATE = """\
Read the following tutor response and extract flashcard candidates.

Your output MUST be a single JSON object matching this schema:

{{
  "cards": [
    {{
      "front": "Short question (<=200 chars)",
      "back": "Short answer (<=500 chars)",
      "concept_slug": "optional-kebab-case-id-or-null"
    }},
    ...
  ]
}}

Hard rules:
- 0 to 3 cards. Zero is the correct answer when the response is not
  teaching-style (just acknowledgment, refusal, clarification question,
  or off-topic). An empty "cards" array is preferred over weak cards.
- Use ONLY facts that appear in the tutor response below. Do NOT invent,
  do NOT draw on external knowledge, do NOT extrapolate beyond what is
  said.
- Each "front" is a single standalone question (≤200 chars). Avoid
  pronouns that need the prior response for context ("what is *it*?").
- Each "back" is a concise answer (≤500 chars) sourced from the response.
- "concept_slug" is optional. If you can identify a single stable
  kebab-case topic label this card belongs to, include it; otherwise set
  it to null or omit it.

Style rules:
- Prefer concepts that are CORE to the topic being taught, not throwaway
  examples.
- Prefer "what is X?" / "how does X work?" / "why does X happen?" framings
  over trivia like "what was mentioned second?".
- Do not produce near-duplicate cards.

Context (for your information, not a source of facts):
- course_id: {course_id}
- grounded_chunks: {chunk_count}

Tutor response:
---
{response_text}
---
"""


# ── Helpers ─────────────────────────────────────────────────


def _extract_json_object(raw: str) -> str | None:
    """Carve a JSON object out of an LLM response.

    Same trick as ``syllabus_builder``: LLMs wrap structured output in
    markdown fences or trailing prose despite instructions. We grab the
    span from the first ``{`` to the last ``}`` — ``json.loads`` on the
    result is still the source of truth.
    """

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    return raw[start : end + 1]


def _build_prompt(
    response_text: str,
    course_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
) -> str:
    """Render the user prompt body. ``course_id`` and chunk count are
    embedded as metadata hints — NOT as source material — so the LLM can
    lean toward course-relevant terminology without treating the context
    line as facts to memorise."""

    trimmed = response_text.strip()
    if len(trimmed) > _RESPONSE_CHAR_CAP:
        trimmed = trimmed[:_RESPONSE_CHAR_CAP].rstrip() + " …"
    return _USER_PROMPT_TEMPLATE.format(
        course_id=str(course_id),
        chunk_count=len(chunk_ids),
        response_text=trimmed,
    )


def _is_trivial_response(response_text: str) -> bool:
    """Guard: skip the LLM entirely for responses too short to contain
    recall-worthy material. Keeps us from burning a provider call on
    "ok", "got it", "I don't know", etc."""

    return len(response_text.strip()) < _TRIVIAL_RESPONSE_MIN_CHARS


async def _call_llm_once(system_prompt: str, user_prompt: str) -> str | None:
    """One round-trip to the LLM. Returns raw text or ``None`` on
    transport error. Mirrors the ``syllabus_builder`` helper."""

    try:
        client = get_llm_client("fast")
    except (ImportError, RuntimeError) as exc:
        logger.warning("card_spawner: LLM client unavailable (%s)", exc)
        return None

    try:
        raw, _ = await client.extract(system_prompt, user_prompt)
    except (ConnectionError, TimeoutError) as exc:
        logger.warning("card_spawner: LLM network error (%s)", exc)
        return None
    except (ValueError, RuntimeError) as exc:
        logger.warning("card_spawner: LLM call failed (%s)", exc)
        return None
    return raw


def _parse_batch(raw: str) -> CardBatch | None:
    """JSON-decode + pydantic-validate an LLM response. ``None`` on failure."""

    payload = _extract_json_object(raw)
    if payload is None:
        logger.debug("card_spawner: no JSON object found in response")
        return None

    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.debug("card_spawner: JSON decode failed: %s", exc)
        return None

    try:
        return CardBatch.model_validate(obj)
    except ValidationError as exc:
        logger.debug("card_spawner: pydantic validation failed: %s", exc)
        return None


async def _attempt_loop(system_prompt: str, user_prompt: str) -> list[CardCandidate]:
    """Run up to ``_MAX_ATTEMPTS`` attempts. Returns the parsed card list
    on first success, or ``[]`` if all attempts fail. This is the body
    that ``asyncio.wait_for`` wraps for the 8-second budget."""

    for attempt in range(_MAX_ATTEMPTS):
        raw = await _call_llm_once(system_prompt, user_prompt)
        if raw is None:
            # Transport-level failure — retry makes sense (transient).
            continue

        batch = _parse_batch(raw)
        if batch is not None:
            # Defensive truncation: schema enforces max_length=3 already,
            # but if that ever changes we still honour the contract here.
            cards = batch.cards[:_MAX_CARDS]
            logger.info(
                "card_spawner: extracted %d card(s) on attempt %d",
                len(cards),
                attempt + 1,
            )
            return cards

        logger.debug(
            "card_spawner: attempt %d/%d failed validation",
            attempt + 1,
            _MAX_ATTEMPTS,
        )

    logger.warning("card_spawner: all %d attempts failed, returning []", _MAX_ATTEMPTS)
    return []


# ── Public API ──────────────────────────────────────────────


async def extract_card_candidates(
    response_text: str,
    chunk_ids: list[uuid.UUID],
    course_id: uuid.UUID,
) -> list[CardCandidate]:
    """Extract 0-3 flashcard candidates from a tutor response.

    Entirely stateless — no DB access, no FSRS writes. The orchestrator
    (T5/T6) is responsible for caching the result and letting the learner
    confirm which cards to persist.

    Budget: ≤8s wall-clock including one retry. Every failure mode
    (trivial input, transport error, timeout, validation failure, all
    attempts exhausted) yields an empty list — this function never
    raises.

    Args:
        response_text: Full tutor reply as emitted to the learner.
        chunk_ids: UUIDs of the RAG chunks that grounded the response.
            Passed in as a prompt metadata hint (count only); not queried.
        course_id: UUID of the course the chat is scoped to. Passed to
            the prompt as a hint.

    Returns:
        A list of 0 to 3 validated ``CardCandidate`` items. Empty list
        is a legitimate result (trivial/non-teaching response, or all
        attempts failed).
    """

    if _is_trivial_response(response_text):
        logger.debug(
            "card_spawner: skipping trivial response (%d chars stripped)",
            len(response_text.strip()),
        )
        return []

    user_prompt = _build_prompt(response_text, course_id, chunk_ids)

    try:
        return await asyncio.wait_for(
            _attempt_loop(_SYSTEM_PROMPT, user_prompt),
            timeout=_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "card_spawner: timed out after %.1fs budget, returning []",
            _TIMEOUT_SEC,
        )
        return []


__all__ = ["extract_card_candidates"]
