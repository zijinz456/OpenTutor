"""Answer-grading strategies for the evaluation harness.

Four modes are supported:

* ``exact``    — case-insensitive string equality after stripping whitespace.
* ``contains`` — substring membership (case-insensitive).
* ``regex``    — ``re.search`` with ``IGNORECASE | DOTALL``.
* ``judge``    — secondary LLM call asking whether the actual answer
  satisfies the expected criterion. Intended for open-ended prompts
  where string matching is too brittle. Falls back to ``contains`` when
  no LLM client is available so unit tests can exercise the path.

All modes return ``bool``; individual regex-compile failures degrade to
``False`` rather than raising, so a malformed fixture never crashes the
suite.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

GradeMode = Literal["exact", "regex", "contains", "judge"]


def grade_answer(expected: str, actual: str, mode: GradeMode) -> bool:
    """Return ``True`` if ``actual`` satisfies ``expected`` under ``mode``."""
    if mode == "exact":
        return expected.strip().lower() == actual.strip().lower()

    if mode == "contains":
        return expected.strip().lower() in actual.lower()

    if mode == "regex":
        try:
            return re.search(expected, actual, re.IGNORECASE | re.DOTALL) is not None
        except re.error as exc:
            # Malformed pattern in fixture — log once and fail the question
            # rather than crashing the whole suite.
            logger.warning("Invalid regex in expected=%r: %s", expected, exc)
            return False

    if mode == "judge":
        # Judge mode intentionally does NOT import an LLM client at module
        # import time — keeps the grader cheap to import in tests. The
        # async variant ``grade_answer_judge`` below performs the real call.
        return expected.strip().lower() in actual.lower()

    logger.warning("Unknown grade_mode=%r, falling back to contains", mode)
    return expected.strip().lower() in actual.lower()


async def grade_answer_judge(
    prompt: str,
    expected: str,
    actual: str,
    *,
    llm_client=None,  # duck-typed LLMClient (services.llm.base_client)
) -> bool:
    """Secondary-LLM judge grading.

    The judge sees the original prompt, the expected-answer criterion, and
    the actual response, and is asked a binary question. Any non-"YES"
    reply is treated as failure. If no client is supplied or the call
    raises, we degrade to ``contains`` grading — the harness must never
    die on a judge-mode question.
    """
    if llm_client is None:
        return grade_answer(expected, actual, "contains")

    system = (
        "You are a strict grader. Answer with exactly one word: YES or NO. "
        "Say YES if the candidate answer correctly addresses the question "
        "and matches the expected criterion; otherwise NO."
    )
    user = (
        f"Question:\n{prompt}\n\n"
        f"Expected (criterion):\n{expected}\n\n"
        f"Candidate answer:\n{actual}\n\n"
        "Verdict (YES or NO):"
    )
    try:
        content, _usage = await llm_client.extract(system, user)
    except Exception as exc:  # noqa: BLE001 — judge must never crash the suite
        logger.warning("Judge LLM call failed: %s", exc)
        return grade_answer(expected, actual, "contains")

    return content.strip().upper().startswith("YES")
