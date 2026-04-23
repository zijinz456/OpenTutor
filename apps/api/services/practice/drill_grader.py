"""LLM-rubric grader for Python Depth ``apply`` / ``compare`` drill styles
(§16.2 + §26 Phase 3).

``trace`` and ``rebuild`` are exact-match after normalization — no LLM needed
and handled inline in ``routers.quiz_submission``. ``apply`` (rewrite a snippet
using a target feature) and ``compare`` (pick the right tool + justify) are
open-ended enough that exact-match would reject valid answers that use
different whitespace, variable names, or alternate-but-correct reasoning.

Follows the same degrade-gracefully contract as ``lab_grader``: one Groq
round-trip per grade, one retry on malformed JSON, never raises. On any
failure the helper returns ``DrillGradeResult(passed=False, confidence=0.0,
explanation="grader unavailable")`` so the router can record a wrong answer
without surfacing a 500 to the user.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)


# ── Result schema ────────────────────────────────────────────


class DrillGradeResult(BaseModel):
    """Outcome of a single drill-grading round-trip."""

    passed: bool = Field(
        ..., description="True only if the answer satisfies the rubric."
    )
    explanation: str = Field(
        ..., description="One-sentence justification shown to the learner."
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Grader's self-reported confidence."
    )


_FALLBACK = DrillGradeResult(
    passed=False,
    confidence=0.0,
    explanation="grader unavailable",
)


# ── Prompt shape ─────────────────────────────────────────────

_APPLY_SYSTEM_PROMPT = (
    "You grade Python code-transformation answers. The learner was asked to "
    "rewrite a starter snippet using a specific target feature (e.g. rewrite a "
    "sync function using asyncio, rewrite a for-loop as a list comprehension). "
    "Mark PASS only if the learner's answer:\n"
    "  1. actually uses the requested target feature,\n"
    "  2. is semantically equivalent to the reference solution,\n"
    "  3. is syntactically valid Python.\n"
    "Trivial whitespace / variable-name differences are OK. A textual "
    "restatement of the reference without actually applying the target "
    "feature is NOT a pass.\n"
    "Return JSON ONLY. No markdown fences, no prose outside JSON. "
    'Schema: {"passed": bool, "explanation": str, "confidence": number}.'
)

_COMPARE_SYSTEM_PROMPT = (
    "You grade Python design-tradeoff answers. The learner was asked to pick "
    "one of two approaches for a given scenario and justify it in one line. "
    "Mark PASS if the learner picks the same option as the reference AND "
    "gives a justification that names a real reason (performance, clarity, "
    "correctness, idiom). If the reference is ambiguous, accept either option "
    "provided the justification is sound.\n"
    "Reject answers that only name an option with no reason, or cite a "
    "clearly wrong reason (e.g. 'threads are always faster').\n"
    "Return JSON ONLY. No markdown fences, no prose outside JSON. "
    'Schema: {"passed": bool, "explanation": str, "confidence": number}.'
)


def _build_user_prompt(*, question: str, reference: str, user_answer: str) -> str:
    """Format the rubric prompt. Uses ``!r`` so the LLM sees quotes around
    user-provided strings (helps it notice empty / whitespace-only input).
    """
    return (
        f"Question: {question}\n"
        f"Reference answer:\n{reference}\n"
        f"Learner answer: {user_answer!r}\n"
        "\n"
        "Is the learner's answer correct under the rubric? Be strict but fair.\n"
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


def _parse_result(raw: str) -> DrillGradeResult | None:
    """Best-effort parse. Returns ``None`` if the response can't be decoded."""
    json_blob = _extract_json_object(raw)
    if json_blob is None:
        return None
    try:
        obj: Any = json.loads(json_blob)
    except json.JSONDecodeError:
        return None
    try:
        return DrillGradeResult.model_validate(obj)
    except (ValueError, TypeError):
        return None


async def _call_llm_once(system_prompt: str, user_prompt: str) -> str | None:
    """One Groq round-trip. Returns raw text, or ``None`` on transport error."""
    try:
        client = get_llm_client("fast")
    except (ImportError, RuntimeError) as exc:
        logger.warning("drill_grader: LLM client unavailable (%s)", exc)
        return None

    try:
        raw, _ = await client.extract(system_prompt, user_prompt)
    except (ConnectionError, TimeoutError) as exc:
        logger.warning("drill_grader: LLM network error (%s)", exc)
        return None
    except (ValueError, RuntimeError) as exc:
        logger.warning("drill_grader: LLM call failed (%s)", exc)
        return None
    return raw


# ── Public API ───────────────────────────────────────────────


async def grade_drill_answer(
    *,
    question_type: str,
    question: str,
    reference_answer: str,
    user_answer: str,
) -> DrillGradeResult:
    """Grade an ``apply`` or ``compare`` drill answer.

    Never raises — falls back to ``DrillGradeResult(passed=False,
    confidence=0.0, explanation="grader unavailable")`` on any transport
    error, two consecutive malformed-JSON responses, or LLM-client construction
    failure. Other question types raise ``ValueError`` — the router is
    responsible for routing only ``apply`` / ``compare`` here.
    """
    if question_type == "apply":
        system_prompt = _APPLY_SYSTEM_PROMPT
    elif question_type == "compare":
        system_prompt = _COMPARE_SYSTEM_PROMPT
    else:
        raise ValueError(
            f"grade_drill_answer: unsupported question_type {question_type!r}"
        )

    user_prompt = _build_user_prompt(
        question=question, reference=reference_answer, user_answer=user_answer
    )

    raw = await _call_llm_once(system_prompt, user_prompt)
    if raw is None:
        return _FALLBACK

    result = _parse_result(raw)
    if result is not None:
        return result

    # One retry — a truncated / fenced response won't recover from re-parse alone.
    logger.info("drill_grader: first response malformed, retrying once")
    raw = await _call_llm_once(system_prompt, user_prompt)
    if raw is None:
        return _FALLBACK

    result = _parse_result(raw)
    if result is not None:
        return result

    logger.warning("drill_grader: grader returned malformed JSON twice; falling back")
    return _FALLBACK
