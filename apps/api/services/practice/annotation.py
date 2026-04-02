"""Shared practice problem annotation pipeline.

This module centralizes normalization of question metadata so every source of
`PracticeProblem` records follows the same contract:
- extracted questions from content
- diagnostic/derived questions
- future chat-generated practice questions
"""

from dataclasses import dataclass
import json
import re
import uuid
from typing import Any

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError

from models.practice import PracticeProblem

VALID_QUESTION_TYPES = {
    "mc",
    "tf",
    "short_answer",
    "fill_blank",
    "matching",
    "select_all",
    "free_response",
    "coding",
}

VALID_BLOOM_LEVELS = {
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
}

_PLACEHOLDER_METADATA_VALUES = {
    "",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "general concept",
    "main concept",
    "main idea",
    "concept",
    "topic",
}

_DEFAULT_BLOOM_BY_TYPE = {
    "mc": "understand",
    "tf": "understand",
    "short_answer": "analyze",
    "fill_blank": "remember",
    "matching": "understand",
    "select_all": "analyze",
    "free_response": "apply",
    "coding": "apply",
}

_DEFAULT_SKILL_BY_TYPE = {
    "mc": "concept check",
    "tf": "verification",
    "short_answer": "explanation",
    "fill_blank": "recall",
    "matching": "association",
    "select_all": "discrimination",
    "free_response": "application",
    "coding": "implementation",
}

_VALID_BLOOM_BY_DIFFICULTY = {
    1: {"remember", "understand", "apply"},
    2: {"understand", "apply", "analyze"},
    3: {"apply", "analyze", "evaluate", "create"},
}


def _default_bloom_level(question_type: str) -> str:
    return _DEFAULT_BLOOM_BY_TYPE.get(question_type, "understand")


def _default_skill_focus(question_type: str) -> str:
    return _DEFAULT_SKILL_BY_TYPE.get(question_type, "understanding")


def _clean_string(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_bloom_level(value: Any, question_type: str) -> str:
    candidate = _clean_string(value).lower()
    if candidate in VALID_BLOOM_LEVELS:
        return candidate
    return _default_bloom_level(question_type)


def _extract_named_concept(question_text: str) -> str:
    question_text = _clean_string(question_text)
    if not question_text:
        return ""
    match = re.search(
        r"(?:what is|what does|why does|how does|when does|which|explain|describe|compare|define)\s+(.+?)(?:\?|$)",
        question_text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    candidate = re.sub(
        r"^(the|a|an)\s+",
        "",
        match.group(1),
        flags=re.IGNORECASE,
    )
    candidate = re.sub(
        r"^(why|how|whether|if|that)\s+",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    candidate = re.split(r"\b(?:for|in|when|while|using|during|before|after)\b", candidate, maxsplit=1)[0]
    return _clean_string(candidate).rstrip(":?.!")


def _normalize_core_concept(value: Any, *, title: str, question_text: str) -> str:
    candidate = _clean_string(value)
    lowered = candidate.lower()
    if lowered in _PLACEHOLDER_METADATA_VALUES or len(candidate) < 3:
        candidate = _extract_named_concept(question_text) or _clean_string(title)
    return candidate or _clean_string(title) or "Core concept"


def _normalize_source_section(value: Any, title: str) -> str:
    candidate = _clean_string(value)
    return candidate or _clean_string(title) or "Untitled section"


def _normalize_skill_focus(value: Any, question_type: str) -> str:
    candidate = _clean_string(value)
    return candidate or _default_skill_focus(question_type)


def _normalize_layer_justification(value: Any, difficulty_layer: int) -> str:
    candidate = _clean_string(value)
    if candidate:
        return candidate
    return f"Generated as layer {difficulty_layer} based on the cognitive demand of the question."


def _normalize_text_answer(value: Any) -> str | None:
    candidate = _clean_string(value)
    return candidate or None


def _normalize_mc_answer(value: Any, options: dict[str, str] | None) -> str | None:
    if options is None:
        return _normalize_text_answer(value)

    candidate = _clean_string(value)
    if not candidate:
        return None

    labels = {key.upper(): key for key in options}
    normalized_candidate = candidate.upper()
    if normalized_candidate in labels:
        return labels[normalized_candidate]

    label_match = re.match(r"^([A-Z])\b", normalized_candidate)
    if label_match and label_match.group(1) in labels:
        return labels[label_match.group(1)]

    for key, option_text in options.items():
        if candidate.casefold() == option_text.casefold():
            return key
    return candidate


def _normalize_tf_answer(value: Any) -> str | None:
    candidate = _clean_string(value).lower()
    if candidate in {"true", "t", "yes"}:
        return "True"
    if candidate in {"false", "f", "no"}:
        return "False"
    return _normalize_text_answer(value)


def build_question_dedupe_key(question: str) -> str:
    """Build a stable question key for duplicate detection."""
    return re.sub(r"[^a-z0-9]+", " ", _clean_string(question).lower()).strip()


class ProblemMetadataContract(BaseModel):
    core_concept: str = Field(min_length=3)
    bloom_level: str
    potential_traps: list[str] = Field(default_factory=list)
    layer_justification: str = Field(min_length=3)
    skill_focus: str = Field(min_length=2)
    source_section: str = Field(min_length=1)
    question_type: str


class QuizQuestionContract(BaseModel):
    question_type: str
    question: str = Field(min_length=8)
    options: dict[str, str] | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    difficulty_layer: int
    problem_metadata: ProblemMetadataContract


@dataclass
class QuizQuestionValidation:
    question: dict[str, Any] | None
    errors: list[str]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0 and self.question is not None


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
    question_type = _clean_string(question.get("question_type") or "mc").lower() or "mc"
    if question_type not in VALID_QUESTION_TYPES:
        question_type = "mc"

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

    normalized_question = _clean_string(question.get("question"))
    normalized_options = normalize_question_options(question.get("options"))
    if question_type == "tf":
        normalized_answer = _normalize_tf_answer(question.get("correct_answer"))
    elif question_type in {"mc", "select_all"}:
        normalized_answer = _normalize_mc_answer(question.get("correct_answer"), normalized_options)
    else:
        normalized_answer = _normalize_text_answer(question.get("correct_answer"))

    normalized_metadata = {
        "core_concept": _normalize_core_concept(
            metadata.get("core_concept") or metadata.get("core_concept_preserved"),
            title=title,
            question_text=normalized_question,
        ),
        "bloom_level": _normalize_bloom_level(metadata.get("bloom_level"), question_type),
        "potential_traps": [str(item).strip() for item in traps if str(item).strip()],
        "layer_justification": _normalize_layer_justification(
            metadata.get("layer_justification"),
            difficulty_layer,
        ),
        "skill_focus": _normalize_skill_focus(metadata.get("skill_focus"), question_type),
        "source_section": _normalize_source_section(metadata.get("source_section"), title),
        "question_type": question_type,
    }
    if source:
        normalized_metadata["source_kind"] = source
    if extra_metadata:
        normalized_metadata.update(extra_metadata)

    return {
        "question_type": question_type,
        "question": normalized_question,
        "options": normalized_options,
        "correct_answer": normalized_answer,
        "explanation": _normalize_text_answer(question.get("explanation")),
        "difficulty_layer": difficulty_layer,
        "problem_metadata": normalized_metadata,
    }


def validate_question_payload(
    question: dict[str, Any],
    *,
    title: str,
    source: str | None = None,
    difficulty_layer_default: int | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> QuizQuestionValidation:
    """Validate a quiz payload after normalization.

    Returns the normalized payload plus machine-actionable errors.
    """
    normalized = normalize_problem_annotation(
        question,
        title=title,
        source=source,
        difficulty_layer_default=difficulty_layer_default,
        extra_metadata=extra_metadata,
    )

    errors: list[str] = []
    try:
        QuizQuestionContract.model_validate(normalized)
    except PydanticValidationError as exc:
        for issue in exc.errors():
            loc = ".".join(str(part) for part in issue.get("loc", []))
            errors.append(f"{loc or 'question'}: {issue.get('msg', 'invalid value')}")

    question_type = normalized["question_type"]
    options = normalized["options"]
    correct_answer = normalized["correct_answer"]
    explanation = normalized["explanation"]
    metadata = normalized["problem_metadata"]

    if normalized["difficulty_layer"] not in (1, 2, 3):
        errors.append("difficulty_layer: must be 1, 2, or 3")
    if metadata.get("bloom_level") not in VALID_BLOOM_LEVELS:
        errors.append("problem_metadata.bloom_level: must be a supported Bloom level")
    elif metadata.get("bloom_level") not in _VALID_BLOOM_BY_DIFFICULTY.get(normalized["difficulty_layer"], VALID_BLOOM_LEVELS):
        errors.append("problem_metadata.bloom_level: does not fit the selected difficulty_layer")

    if not explanation or len(explanation) < 6:
        errors.append("explanation: must be present and informative")

    if question_type == "mc":
        if not options or len(options) != 4:
            errors.append("options: multiple-choice questions require exactly 4 options")
        elif correct_answer not in options:
            errors.append("correct_answer: must match one of the multiple-choice option labels")
    elif question_type == "select_all":
        if not options or len(options) < 4:
            errors.append("options: select-all questions require at least 4 options")
        labels = []
        if isinstance(correct_answer, str):
            labels = [item.strip().upper() for item in re.split(r"[,/;|]", correct_answer) if item.strip()]
        if len(labels) < 2:
            errors.append("correct_answer: select-all questions require at least 2 correct labels")
        elif options and any(label not in {key.upper() for key in options} for label in labels):
            errors.append("correct_answer: select-all labels must match the provided options")
    elif question_type == "tf":
        if correct_answer not in {"True", "False"}:
            errors.append("correct_answer: true/false questions must answer True or False")
    elif question_type == "matching":
        if not options or len(options) < 2:
            errors.append("options: matching questions require at least 2 pairs or prompts")
        if not correct_answer:
            errors.append("correct_answer: matching questions require an answer key")
    else:
        if not correct_answer:
            errors.append("correct_answer: must be present")

    return QuizQuestionValidation(
        question=normalized if not errors else normalized,
        errors=errors,
    )


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
