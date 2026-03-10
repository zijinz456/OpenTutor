"""Shared diagnostic question derivation logic.

Used by both the quiz auto-derive background task and the wrong_answers
derive endpoint. Generates simplified "clean" diagnostic versions of
questions that students answered incorrectly.
"""

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import WrongAnswer
from models.practice import PracticeProblem
from services.practice.annotation import build_practice_problem

logger = logging.getLogger(__name__)

_DERIVE_SYSTEM = "You design diagnostic questions. Output valid JSON only."

_DERIVE_PROMPT = """You are a diagnostic question designer. A student got this question wrong.
Generate a SIMPLIFIED "clean" diagnostic version that:
1. Tests the EXACT SAME core concept
2. Removes all distractors, traps, and misleading wording
3. Uses simpler numbers/context
4. If multi-step, only keep the key step

Original question: {question}
Question type: {question_type}
Correct answer: {correct_answer}
Student's wrong answer: {user_answer}
Error category: {error_category}
{metadata_str}

Return JSON only:
{{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}} or null, "correct_answer": "...", "explanation": "...", "simplifications_made": ["list of specific simplifications"], "core_concept_preserved": "name of the core concept being tested"}}"""


def _build_metadata_str(problem: PracticeProblem) -> str:
    """Build metadata context string for the LLM prompt."""
    if not problem.problem_metadata:
        return ""
    meta = problem.problem_metadata
    parts = []
    if meta.get("core_concept"):
        parts.append(f"Core concept: {meta['core_concept']}")
    if meta.get("potential_traps"):
        parts.append(f"Known traps to remove: {', '.join(meta['potential_traps'])}")
    if meta.get("bloom_level"):
        parts.append(f"Bloom's level: {meta['bloom_level']}")
    if not parts:
        return ""
    return "\nQuestion metadata (use to guide simplification):\n" + "\n".join(parts)


def _extract_json_object(text: str) -> dict:
    """Extract the first balanced JSON object from mixed LLM output."""
    start = text.find("{")
    if start == -1:
        return {"question": text}
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    if "question" in obj:
                        return obj
                except json.JSONDecodeError:
                    pass
    return {"question": text}


def _fill_defaults(derived: dict, wa: WrongAnswer, problem: PracticeProblem) -> dict:
    """Fill in missing fields from the LLM response with sensible defaults."""
    if not derived.get("question"):
        derived["question"] = f"Diagnostic check: {problem.question}"
    if derived.get("options") is None and problem.options:
        derived["options"] = problem.options
    if not derived.get("correct_answer"):
        derived["correct_answer"] = wa.correct_answer or problem.correct_answer
    if not derived.get("explanation"):
        derived["explanation"] = (
            "This simplified follow-up checks whether the core concept is understood "
            "without the original traps or extra complexity."
        )
    if not derived.get("core_concept_preserved"):
        derived["core_concept_preserved"] = (
            (problem.problem_metadata or {}).get("core_concept")
            or problem.question[:80]
        )
    if not derived.get("simplifications_made"):
        derived["simplifications_made"] = ["Fallback diagnostic variant based on the original question."]
    return derived


async def derive_diagnostic(
    db: AsyncSession,
    wa: WrongAnswer,
    problem: PracticeProblem,
) -> PracticeProblem:
    """Generate and persist a diagnostic pair for a wrong answer.

    Returns the newly created diagnostic PracticeProblem.
    """
    from services.llm.router import get_llm_client

    client = get_llm_client()
    metadata_str = _build_metadata_str(problem)

    prompt = _DERIVE_PROMPT.format(
        question=problem.question,
        question_type=problem.question_type,
        correct_answer=wa.correct_answer,
        user_answer=wa.user_answer,
        error_category=wa.error_category or "unknown",
        metadata_str=metadata_str,
    )

    response, _ = await client.chat(_DERIVE_SYSTEM, prompt)

    from libs.text_utils import parse_llm_json

    derived = parse_llm_json(response, default=None)
    if not isinstance(derived, dict) or "question" not in derived:
        derived = _extract_json_object(response)

    derived = _fill_defaults(derived, wa, problem)

    extra_metadata = {
        "simplifications_made": derived.get("simplifications_made", []),
        "core_concept_preserved": derived.get("core_concept_preserved", ""),
        "original_problem_id": str(problem.id),
        "wrong_answer_id": str(wa.id),
    }
    new_problem = build_practice_problem(
        course_id=problem.course_id,
        content_node_id=problem.content_node_id,
        title=(problem.problem_metadata or {}).get("core_concept", problem.question[:80]),
        question={
            "question_type": problem.question_type,
            "question": derived.get("question", ""),
            "options": derived.get("options"),
            "correct_answer": derived.get("correct_answer"),
            "explanation": derived.get("explanation"),
            "difficulty_layer": 1,
            "problem_metadata": {
                "core_concept": derived.get("core_concept_preserved")
                or (problem.problem_metadata or {}).get("core_concept")
                or problem.question[:80],
                "bloom_level": "understand",
                "potential_traps": [],
                "layer_justification": "Simplified diagnostic variant for isolating the core concept.",
                "skill_focus": "core concept check",
                "source_section": (problem.problem_metadata or {}).get("source_section", "Diagnostic follow-up"),
            },
        },
        order_index=problem.order_index,
        knowledge_points=wa.knowledge_points or problem.knowledge_points,
        source="derived",
        parent_problem_id=problem.id,
        is_diagnostic=True,
        difficulty_layer_default=1,
        extra_metadata=extra_metadata,
    )
    db.add(new_problem)
    return new_problem
