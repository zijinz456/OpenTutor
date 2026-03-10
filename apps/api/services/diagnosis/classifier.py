"""Structured error classification using LLM with tool schema constraints.

VCE engineering pattern: instead of letting LLM output free-text error analysis,
force structured output with {category, confidence, evidence, related_concept}.
This data becomes immutable annotation stored in WrongAnswer.error_detail,
used as grounding context by ReviewAgent and AssessmentAgent.

Borrows from:
- VCE annotation_errors: pre-labeled error types constrain AI
- HelloAgents ToolParameter: schema-constrained tool output
- OpenAkita SemanticMemory: entity-attribute structured facts
"""

import json
import logging

logger = logging.getLogger(__name__)

_VALID_CATEGORIES = {"conceptual", "procedural", "computational", "reading", "careless"}

_CLASSIFICATION_PROMPT = """Classify this student's error into exactly ONE category.
Return ONLY a valid JSON object, nothing else.

Categories:
- conceptual: Misunderstanding of the core concept or definition
- procedural: Wrong method, wrong steps, or wrong formula applied
- computational: Correct approach but arithmetic/calculation error
- reading: Misread the question, missed a condition, or confused units
- careless: Simple typo, sign error, or obvious oversight

Question: {question}
Correct answer: {correct_answer}
Student's answer: {user_answer}
{metadata_context}

Return JSON:
{{"category": "one_of_the_five", "confidence": 0.0_to_1.0, "evidence": "brief explanation of why this category", "related_concept": "the concept being tested"}}"""


async def classify_error(
    question: str,
    correct_answer: str,
    user_answer: str,
    problem_metadata: dict | None = None,
) -> dict:
    """Classify a student error into structured categories.

    Uses a lightweight LLM call with schema-constrained output.
    The result is stored as immutable annotation, not re-computed later.

    Returns:
        {
            "category": str,       # one of 5 categories
            "confidence": float,   # 0.0-1.0
            "evidence": str,       # why this classification
            "related_concept": str # concept being tested
        }
    """
    from services.llm.router import get_llm_client

    # Build metadata context for grounding (VCE pattern: use existing annotations)
    metadata_context = ""
    if problem_metadata:
        parts = []
        if problem_metadata.get("core_concept"):
            parts.append(f"Core concept: {problem_metadata['core_concept']}")
        if problem_metadata.get("potential_traps"):
            parts.append(f"Known traps: {', '.join(problem_metadata['potential_traps'])}")
        if problem_metadata.get("difficulty_layer"):
            parts.append(f"Difficulty layer: {problem_metadata['difficulty_layer']}")
        if parts:
            metadata_context = "Question metadata (verified facts, do not contradict):\n" + "\n".join(parts)

    prompt = _CLASSIFICATION_PROMPT.format(
        question=question,
        correct_answer=correct_answer,
        user_answer=user_answer,
        metadata_context=metadata_context,
    )

    try:
        client = get_llm_client("fast")
        response, _ = await client.chat(
            "You classify student errors. Return only valid JSON, nothing else.",
            prompt,
        )

        result = _parse_classification(response)
        return result
    except (ConnectionError, TimeoutError, ValueError, KeyError, RuntimeError, OSError) as e:
        logger.exception("Error classification LLM call failed")
        return {
            "category": "conceptual",
            "confidence": 0.3,
            "evidence": f"Classification failed: {e}",
            "related_concept": "unknown",
        }


def _parse_classification(response: str) -> dict:
    """Parse and validate LLM classification output."""
    from libs.text_utils import parse_llm_json

    fallback = {
        "category": "conceptual",
        "confidence": 0.3,
        "evidence": response.strip(),
        "related_concept": "unknown",
    }
    result = parse_llm_json(response, default=None)
    if not isinstance(result, dict):
        return fallback

    # Validate and normalize
    category = result.get("category", "conceptual").strip().lower()
    if category not in _VALID_CATEGORIES:
        category = "conceptual"

    confidence = result.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5
    confidence = max(0.0, min(1.0, float(confidence)))

    return {
        "category": category,
        "confidence": confidence,
        "evidence": str(result.get("evidence", "")),
        "related_concept": str(result.get("related_concept", "unknown")),
    }
