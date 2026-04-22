"""LLM-rubric grader for hacking-lab submissions (§34.6 Phase 12).

Single Groq call per proof. Strict rubric — garbage input must fail. On malformed
JSON, re-invoke the LLM once (re-parse alone wouldn't recover from a truncated
response). On transport/network errors or repeat JSON failure, degrade gracefully
to ``passed=False, confidence=0.0, explanation="grader unavailable"`` so the
router never surfaces a 500 to the user.

The grader doesn't care about the specific lab; it grades plausibility from:
  * the problem's textual task description (problem.question)
  * the expected artifact type from problem_metadata (e.g. "XSS payload",
    "SQL injection", "flag string")
  * the user's submitted payload + flag-or-evidence pair

Intentionally rejected by design:
  * empty payload or evidence
  * evidence that looks like a placeholder ("idk", "solved", "xyz")
  * evidence that contradicts the expected artifact type
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from schemas.quiz import LabExerciseSubmitPayload
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


# ── Result schema ────────────────────────────────────────────


class LabGradeResult(BaseModel):
    """Outcome of a single grading round-trip."""

    passed: bool = Field(
        ..., description="True only if the proof is plausibly a real solve."
    )
    explanation: str = Field(
        ..., description="One-sentence justification shown to the learner."
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Grader's self-reported confidence."
    )


_FALLBACK = LabGradeResult(
    passed=False,
    confidence=0.0,
    explanation="grader unavailable",
)


# ── Prompt shape ─────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You grade cybersecurity lab proofs. You are STRICT — a real solve requires "
    "a concrete, specific payload and concrete observed evidence that matches "
    "the expected artifact type. Garbage input (empty strings, placeholders "
    "like 'solved' or 'idk', copy-pasted task text, obviously wrong artifact "
    "types) MUST fail with passed=false.\n"
    "Return JSON ONLY. No markdown fences, no prose outside JSON. "
    'Schema: {"passed": bool, "explanation": str, "confidence": number}.'
)


def _build_user_prompt(
    *, task: str, expected_artifact_type: str, payload: LabExerciseSubmitPayload
) -> str:
    """Format the rubric prompt.

    The ``!r`` wrappers mirror the spec — we want the LLM to see quotes around
    user-provided strings so it can spot an empty payload or lone whitespace.
    """

    return (
        f"Lab task: {task}\n"
        f"Expected artifact type: {expected_artifact_type}\n"
        f"User submitted:\n"
        f"  payload_used = {payload.payload_used!r}\n"
        f"  flag_or_evidence = {payload.flag_or_evidence!r}\n"
        "\n"
        "Is this plausibly a real solve? Be strict.\n"
        "Negative examples that MUST fail:\n"
        '  - payload_used = "" (empty)\n'
        '  - flag_or_evidence = "solved" or "done" or "idk" or other placeholders\n'
        "  - payload that doesn't match the expected artifact type at all\n"
        "    (e.g. expected XSS, user sent a random SQL string)\n"
        "Positive signal:\n"
        "  - payload looks like a real instance of the expected artifact\n"
        "  - evidence describes specific observed behaviour or a plausible flag\n"
        "\n"
        'Return JSON only: {"passed": bool, "explanation": str, "confidence": number}\n'
    )


# ── Helpers ──────────────────────────────────────────────────


def _extract_json_object(raw: str) -> str | None:
    """Carve a JSON object out of an LLM response. Tolerant of markdown fences."""

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return raw[start : end + 1]


def _parse_result(raw: str) -> LabGradeResult | None:
    """Best-effort parse. Returns ``None`` if the response can't be decoded."""

    json_blob = _extract_json_object(raw)
    if json_blob is None:
        return None
    try:
        obj: Any = json.loads(json_blob)
    except json.JSONDecodeError:
        return None
    try:
        return LabGradeResult.model_validate(obj)
    except (ValueError, TypeError):
        return None


async def _call_llm_once(system_prompt: str, user_prompt: str) -> str | None:
    """One Groq round-trip. Returns raw text, or ``None`` on transport error."""

    try:
        client = get_llm_client("fast")
    except (ImportError, RuntimeError) as exc:
        logger.warning("lab_grader: LLM client unavailable (%s)", exc)
        return None

    try:
        raw, _ = await client.extract(system_prompt, user_prompt)
    except (ConnectionError, TimeoutError) as exc:
        logger.warning("lab_grader: LLM network error (%s)", exc)
        return None
    except (ValueError, RuntimeError) as exc:
        logger.warning("lab_grader: LLM call failed (%s)", exc)
        return None
    return raw


# ── Public API ───────────────────────────────────────────────


async def grade_lab_proof(
    db: Any,  # AsyncSession — untyped so the stubbed unit tests can pass None
    problem: Any,
    payload: LabExerciseSubmitPayload,
) -> LabGradeResult:
    """Grade a single lab proof via Groq. Never raises — falls back to
    ``LabGradeResult(passed=False, confidence=0.0, explanation="grader unavailable")``
    on any transport error, on two consecutive malformed-JSON responses, or on
    an LLM client construction failure.

    ``db`` is accepted for parity with other practice-layer graders that do
    audit writes; we don't currently use it, but keeping the parameter lets
    future work add persistence without changing every caller.
    """

    task = (getattr(problem, "question", None) or "").strip()
    metadata = getattr(problem, "problem_metadata", None) or {}
    expected_artifact_type = str(
        metadata.get("expected_artifact_type") or "solve evidence"
    ).strip()

    system_prompt = _SYSTEM_PROMPT
    user_prompt = _build_user_prompt(
        task=task, expected_artifact_type=expected_artifact_type, payload=payload
    )

    # First attempt.
    raw = await _call_llm_once(system_prompt, user_prompt)
    if raw is None:
        return _FALLBACK

    result = _parse_result(raw)
    if result is not None:
        return result

    # Second attempt — re-invoke (a truncated / fenced response won't recover
    # from re-parsing alone; we need fresh bytes).
    logger.info("lab_grader: first response malformed, retrying once")
    raw = await _call_llm_once(system_prompt, user_prompt)
    if raw is None:
        return _FALLBACK

    result = _parse_result(raw)
    if result is not None:
        return result

    logger.warning("lab_grader: grader returned malformed JSON twice; falling back")
    return _FALLBACK
