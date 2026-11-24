"""LLM-based grader for coding quiz questions.

No code execution — the student's submission is graded purely by the LLM
comparing it against the reference answer and explanation. This is safe
for untrusted code and keeps the system simple.
"""

from __future__ import annotations

import logging

from libs.exceptions import LLMUnavailableError
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

_GRADING_PROMPT = """You are grading a student's code answer.
Evaluate whether the student's code correctly solves the problem.

Rules:
- Accept any correct implementation, not just the reference solution.
- Minor syntax variations (e.g. single vs double quotes, spacing) are fine.
- The logic must be functionally equivalent to the reference, not identical.
- Respond with ONLY a JSON object: {"is_correct": true/false, "feedback": "brief reason"}
- Keep feedback under 30 words."""


async def grade_coding_answer(
    *,
    question: str,
    reference_answer: str,
    user_code: str,
) -> dict:
    """Grade a coding answer using the LLM.

    Returns a dict with:
        is_correct: bool
        feedback: str

    Raises LLMUnavailableError when the provider or its verdict is unavailable.
    """
    if not user_code.strip():
        return {"is_correct": False, "feedback": "No code submitted."}

    user_msg = (
        f"Question: {question}\n\n"
        f"Reference answer:\n{reference_answer}\n\n"
        f"Student's code:\n{user_code}"
    )

    try:
        client = get_llm_client()
        raw, _ = await client.chat(_GRADING_PROMPT, user_msg)
    except Exception as exc:  # Provider SDKs expose different exception types.
        logger.warning("Coding grader LLM call failed (%s)", type(exc).__name__)
        raise LLMUnavailableError(
            "Coding grading is unavailable. Please try again."
        ) from exc

    from libs.text_utils import parse_llm_json
    parsed = parse_llm_json(raw) if isinstance(raw, str) else None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("is_correct"), bool):
        raise LLMUnavailableError(
            "Coding grading returned an invalid result. Please try again."
        )

    return {
        "is_correct": parsed["is_correct"],
        "feedback": str(parsed.get("feedback", "")),
    }
