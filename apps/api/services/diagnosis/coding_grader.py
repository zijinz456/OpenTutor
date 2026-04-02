"""LLM-based grader for coding quiz questions.

No code execution — the student's submission is graded purely by the LLM
comparing it against the reference answer and explanation. This is safe
for untrusted code and keeps the system simple.
"""

from __future__ import annotations

import logging

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
    """
    if not user_code.strip():
        return {"is_correct": False, "feedback": "No code submitted."}

    client = get_llm_client()
    user_msg = (
        f"Question: {question}\n\n"
        f"Reference answer:\n{reference_answer}\n\n"
        f"Student's code:\n{user_code}"
    )

    try:
        raw, _ = await client.chat(_GRADING_PROMPT, user_msg)
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
        logger.warning("Coding grader LLM call failed: %s", exc)
        return {"is_correct": False, "feedback": "Grading unavailable."}

    from libs.text_utils import parse_llm_json
    parsed = parse_llm_json(raw)
    if not isinstance(parsed, dict):
        return {"is_correct": False, "feedback": "Grading parse error."}

    return {
        "is_correct": bool(parsed.get("is_correct", False)),
        "feedback": str(parsed.get("feedback", "")),
    }
