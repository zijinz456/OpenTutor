"""Shared practice problem annotation pipeline.

This module centralizes normalization of question metadata so every source of
`PracticeProblem` records follows the same contract:
- extracted questions from content
- diagnostic/derived questions
- future chat-generated practice questions
"""

import json
import re
import uuid
from typing import Any

from models.practice import PracticeProblem


_DEFAULT_BLOOM_BY_TYPE = {
    "mc": "understand",
    "tf": "understand",
    "short_answer": "analyze",
    "fill_blank": "remember",
    "matching": "understand",
    "select_all": "analyze",
    "free_response": "apply",
}

_DEFAULT_SKILL_BY_TYPE = {
    "mc": "concept check",
    "tf": "verification",
    "short_answer": "explanation",
    "fill_blank": "recall",
    "matching": "association",
    "select_all": "discrimination",
    "free_response": "application",
}


def _default_bloom_level(question_type: str) -> str:
    return _DEFAULT_BLOOM_BY_TYPE.get(question_type, "understand")


def _default_skill_focus(question_type: str) -> str:
    return _DEFAULT_SKILL_BY_TYPE.get(question_type, "understanding")


def normalize_question_options(value: Any) -> dict[str, str] | None:
    """Normalize legacy/mixed option payloads into a clean string map."""
    if value is None:
        return None

    if isinstance(value, dict):
        normalized_dict: dict[str, str] = {}
        for key, item in value.items():
            label = str(key or "").strip()
            if not label or item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            normalized_dict[label] = text
        return normalized_dict or None

    if isinstance(value, list):
        normalized_list: dict[str, str] = {}
        for index, item in enumerate(value):
            if item is None:
                continue
            text = str(item).strip()
            if not text:
                continue
            key = chr(ord("A") + index) if index < 26 else str(index + 1)
            match = re.match(r"^([A-Z])\s*[:.)-]\s*(.+)$", text)
            if match:
                key = match.group(1)
                text = match.group(2).strip()
            if text:
                normalized_list[key] = text
        return normalized_list or None

    return None


def parse_question_array(text: str) -> list[dict[str, Any]]:
    """Extract a JSON array of question objects from raw LLM output."""
    def _normalize_question_payload(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            return [payload]
        return []

    from libs.text_utils import parse_llm_json

    parsed = parse_llm_json(text, default=[])
    return _normalize_question_payload(parsed)


def normalize_problem_annotation(
    question: dict[str, Any],
    *,
    title: str,
    source: str | None = None,
    difficulty_layer_default: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize question payload and metadata into a single contract."""
    question_type = str(question.get("question_type") or "mc").strip() or "mc"

    raw_layer = question.get("difficulty_layer")
    try:
        difficulty_layer = int(raw_layer)
    except (TypeError, ValueError):
        difficulty_layer = difficulty_layer_default
    if difficulty_layer not in (1, 2, 3):
        difficulty_layer = 1 if question_type in {"tf", "fill_blank"} else 2

    metadata = question.get("problem_metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    traps = metadata.get("potential_traps")
    if not isinstance(traps, list):
        traps = []

    normalized_metadata = {
        "core_concept": str(
            metadata.get("core_concept")
            or metadata.get("core_concept_preserved")
            or title
        ).strip(),
        "bloom_level": str(metadata.get("bloom_level") or _default_bloom_level(question_type)).strip().lower(),
        "potential_traps": [str(item).strip() for item in traps if str(item).strip()],
        "layer_justification": str(
            metadata.get("layer_justification")
            or f"Generated as layer {difficulty_layer} based on the cognitive demand of the question."
        ).strip(),
        "skill_focus": str(metadata.get("skill_focus") or _default_skill_focus(question_type)).strip(),
        "source_section": str(metadata.get("source_section") or title).strip(),
        "question_type": question_type,
    }
    if source:
        normalized_metadata["source_kind"] = source
    if extra_metadata:
        normalized_metadata.update(extra_metadata)

    return {
        "question_type": question_type,
        "question": str(question.get("question") or "").strip(),
        "options": normalize_question_options(question.get("options")),
        "correct_answer": question.get("correct_answer"),
        "explanation": question.get("explanation"),
        "difficulty_layer": difficulty_layer,
        "problem_metadata": normalized_metadata,
    }


def build_practice_problem(
    *,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
    title: str,
    question: dict[str, Any],
    order_index: int = 0,
    source: str | None = None,
    knowledge_points: list[str] | None = None,
    parent_problem_id: uuid.UUID | None = None,
    is_diagnostic: bool = False,
    source_batch_id: uuid.UUID | None = None,
    source_version: int = 1,
    is_archived: bool = False,
    difficulty_layer_default: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> PracticeProblem:
    """Build a PracticeProblem using the shared annotation contract."""
    normalized = normalize_problem_annotation(
        question,
        title=title,
        source=source,
        difficulty_layer_default=difficulty_layer_default,
        extra_metadata=extra_metadata,
    )

    return PracticeProblem(
        course_id=course_id,
        content_node_id=content_node_id,
        question_type=normalized["question_type"],
        question=normalized["question"],
        options=normalized["options"],
        correct_answer=normalized["correct_answer"],
        explanation=normalized["explanation"],
        order_index=order_index,
        knowledge_points=knowledge_points,
        source=source,
        difficulty_layer=normalized["difficulty_layer"],
        problem_metadata=normalized["problem_metadata"],
        parent_problem_id=parent_problem_id,
        is_diagnostic=is_diagnostic,
        source_batch_id=source_batch_id,
        source_version=source_version,
        is_archived=is_archived,
    )
