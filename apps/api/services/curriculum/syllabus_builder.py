"""Syllabus builder — one LLM call per URL ingest → topic roadmap.

Part of §14.5 v2.1 (URL → auto-curriculum). After a URL has been scraped
and turned into a ``course_content_tree`` hierarchy, this service collects
the substantive knowledge nodes (level >= 1, non-``info`` category, length
> 100 chars), merges their titles and trimmed content into a single prompt,
and asks the LLM to emit 3-12 topic nodes plus a topo-sorted learning path.

Design notes
------------
* Single LLM call per URL. Retry **once** on validation failure, then bail
  with ``None`` and a warning — the ingestion pipeline (T2) treats ``None``
  as a soft failure and continues without a roadmap.
* Reuses the existing ``services.llm.router.get_llm_client`` abstraction —
  no direct provider calls. Uses the ``"fast"`` variant because the task is
  short-context structured extraction, matching sibling services like
  ``services.loom_extraction`` and ``services.ingestion.classification``.
* Uses ``services.ingestion.content_trimmer.trim_for_llm`` to cap the prompt
  at ~6k tokens regardless of how many content nodes exist.
* Schema validation lives in ``schemas.curriculum.Syllabus`` (slug regex,
  min/max node count, unique slugs, ``depends_on`` dangling-ref check, and
  a real topo-sort check of ``suggested_path``).

This module is deliberately standalone — it is **not** wired into the
ingestion pipeline here. That's T2's job. T1 exposes only
``build_syllabus``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree, INFO_CATEGORIES
from schemas.curriculum import Syllabus
from services.ingestion.content_trimmer import trim_for_llm
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


# ── Tunables ────────────────────────────────────────────────

# Minimum substantive content length (chars) for a tree row to be included
# in the prompt. Rows with ``len(content) <= 100`` are effectively
# empty-section headers and contribute noise, not signal.
_MIN_CONTENT_CHARS = 100

# Per-row content truncation before merging into the mega-prompt. Keeps
# single large chapters from starving the rest of the tree.
_PER_NODE_CHAR_CAP = 1500

# Final token budget for the merged prompt body (excluding system prompt +
# instruction scaffolding). ``trim_for_llm`` enforces this.
_MERGED_PROMPT_TOKEN_BUDGET = 6000

# How many retries on schema-validation failure. One retry = two total
# attempts. Hard-coded — we don't want a loop-knob here.
_MAX_ATTEMPTS = 2

_SYSTEM_PROMPT = (
    "You are a curriculum designer. You read an educational document "
    "(split into sections) and produce a concise topic roadmap. "
    "Output ONLY valid JSON that matches the schema described in the "
    "user message — no prose, no markdown fences, no explanation."
)

_USER_PROMPT_TEMPLATE = """\
Read the following educational document and produce a learning roadmap.

Your output MUST be a single JSON object matching this schema:

{{
  "nodes": [
    {{
      "slug": "kebab-case-id",
      "topic": "Short human-readable topic name (<=80 chars)",
      "blurb": "One-sentence description of what this topic covers (<=200 chars)",
      "depends_on": ["slug-of-prereq-topic", ...]
    }},
    ...
  ],
  "suggested_path": ["slug1", "slug2", ...]
}}

Hard rules:
- 3 to 12 nodes. Fewer than 3 means the document is too thin to teach;
  more than 12 means you are not chunking at the right abstraction level.
- Each "slug" is lowercase kebab-case, 3 to 60 chars, pattern [a-z0-9-].
- All slugs are unique.
- "depends_on" entries must each be a slug that also appears in "nodes".
- A node cannot depend on itself.
- "suggested_path" must list every node slug exactly once, in an order
  that is a valid topological sort: if node X depends on Y, then Y must
  appear before X in the path.

Style rules:
- Topics are noun phrases, not full sentences ("List Comprehensions",
  not "Learning how to use list comprehensions in Python").
- Blurbs describe the concept, not the learning activity
  ("Functions can accept variable-length argument lists via *args and **kwargs"
  not "The learner will discover how *args works").

Document sections:

{merged_content}
"""


# ── Helpers ─────────────────────────────────────────────────


def _extract_json_object(raw: str) -> str | None:
    """Carve a JSON object out of an LLM response.

    LLMs routinely wrap structured output in markdown fences or trailing
    prose despite instructions. We grab the span from the first ``{`` to
    the last ``}`` and hope. ``json.loads`` on the result is still the
    source of truth; this helper just trims obvious garbage.
    """

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    return raw[start : end + 1]


def _build_user_prompt(rows: list[CourseContentTree]) -> str:
    """Merge eligible content rows into a single token-capped prompt body."""

    parts: list[str] = []
    for row in rows:
        # Row.content is non-None + len > 100 by caller's query filter, but
        # mypy-style narrowing can't see that, and ty will complain —
        # narrow explicitly.
        content = row.content or ""
        if len(content) <= _MIN_CONTENT_CHARS:
            continue
        section = f"## {row.title}\n{content[:_PER_NODE_CHAR_CAP].rstrip()}"
        parts.append(section)

    merged = "\n\n---\n\n".join(parts)
    trimmed = trim_for_llm(merged, max_tokens=_MERGED_PROMPT_TOKEN_BUDGET)
    return _USER_PROMPT_TEMPLATE.format(merged_content=trimmed)


async def _fetch_eligible_rows(
    db: AsyncSession, course_id: uuid.UUID
) -> list[CourseContentTree]:
    """Collect knowledge-category content rows with enough substance to teach.

    Filter rationale:
    - ``level >= 1``: exclude the synthetic root row (level 0).
    - ``content_category NOT IN INFO_CATEGORIES``: drop syllabus / assignment /
      exam-schedule rows — they describe logistics, not concepts.
    - ``len(content) > 100``: drop section headers with no real body.
    """

    stmt = (
        select(CourseContentTree)
        .where(
            CourseContentTree.course_id == course_id,
            CourseContentTree.level >= 1,
            CourseContentTree.content.isnot(None),
        )
        .order_by(CourseContentTree.order_index)
    )
    result = await db.execute(stmt)
    all_rows = list(result.scalars().all())

    eligible: list[CourseContentTree] = []
    for row in all_rows:
        if row.content_category in INFO_CATEGORIES:
            continue
        if not row.content or len(row.content) <= _MIN_CONTENT_CHARS:
            continue
        eligible.append(row)
    return eligible


async def _call_llm_once(system_prompt: str, user_prompt: str) -> str | None:
    """One round-trip to the LLM. Returns raw text or ``None`` on transport error."""

    try:
        client = get_llm_client("fast")
    except (ImportError, RuntimeError) as exc:
        logger.warning("syllabus_builder: LLM client unavailable (%s)", exc)
        return None

    try:
        raw, _ = await client.extract(system_prompt, user_prompt)
    except (ConnectionError, TimeoutError) as exc:
        logger.warning("syllabus_builder: LLM network error (%s)", exc)
        return None
    except (ValueError, RuntimeError) as exc:
        logger.warning("syllabus_builder: LLM call failed (%s)", exc)
        return None
    return raw


def _parse_syllabus(raw: str) -> Syllabus | None:
    """JSON-decode + pydantic-validate an LLM response. ``None`` on failure."""

    payload = _extract_json_object(raw)
    if payload is None:
        logger.debug("syllabus_builder: no JSON object found in response")
        return None

    try:
        obj = json.loads(payload)
    except json.JSONDecodeError as exc:
        logger.debug("syllabus_builder: JSON decode failed: %s", exc)
        return None

    try:
        return Syllabus.model_validate(obj)
    except ValidationError as exc:
        logger.debug("syllabus_builder: pydantic validation failed: %s", exc)
        return None


# ── Public API ──────────────────────────────────────────────


async def build_syllabus(db: AsyncSession, course_id: uuid.UUID) -> Syllabus | None:
    """Generate a topic roadmap for an ingested course.

    Collects substantive knowledge rows from ``course_content_tree``, merges
    them into a single token-capped prompt, asks the LLM for a structured
    ``Syllabus``, and retries once on validation failure. Returns the parsed
    syllabus on success or ``None`` (with a warning log) on failure.

    Never raises — the caller (T2 ingestion pipeline) treats ``None`` as a
    soft failure: the URL ingest still succeeds, only the roadmap is
    skipped.

    Args:
        db: Async SQLAlchemy session scoped to the ingesting request.
        course_id: UUID of the course whose content tree should be
            summarised.

    Returns:
        Validated ``Syllabus`` instance, or ``None`` if ingestion has too
        little content or both LLM attempts fail to produce a valid
        payload.
    """

    rows = await _fetch_eligible_rows(db, course_id)
    if len(rows) < 2:
        logger.info(
            "syllabus_builder: course %s has %d eligible rows, skipping",
            course_id,
            len(rows),
        )
        return None

    user_prompt = _build_user_prompt(rows)

    for attempt in range(_MAX_ATTEMPTS):
        raw = await _call_llm_once(_SYSTEM_PROMPT, user_prompt)
        if raw is None:
            # Transport-level failure — retry makes sense (transient).
            continue

        syllabus = _parse_syllabus(raw)
        if syllabus is not None:
            logger.info(
                "syllabus_builder: built %d-node syllabus for course %s on attempt %d",
                len(syllabus.nodes),
                course_id,
                attempt + 1,
            )
            return syllabus

        logger.debug(
            "syllabus_builder: attempt %d/%d failed validation for course %s",
            attempt + 1,
            _MAX_ATTEMPTS,
            course_id,
        )

    logger.warning(
        "syllabus_builder: all %d attempts failed for course %s, returning None",
        _MAX_ATTEMPTS,
        course_id,
    )
    return None


# Re-export the slug regex for callers that want to validate external slug
# inputs (e.g. T2 persistence step) without re-hitting pydantic.
SLUG_PATTERN: re.Pattern[str] = re.compile(r"^[a-z0-9-]{3,60}$")


__all__ = ["build_syllabus", "SLUG_PATTERN"]
