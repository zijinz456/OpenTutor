from __future__ import annotations

"""Quiz extraction service.

Extracts practice problems from content using structured LLM output and writes
consistent problem metadata for downstream review, assessment, and mastery
tracking. The metadata schema is generic learning analytics, not domain-specific.
"""

from dataclasses import dataclass, field
import logging
import math
from typing import Any
import uuid

from models.practice import PracticeProblem
from services.llm.router import get_llm_client
from services.practice.annotation import (
    build_practice_problem,
    build_question_dedupe_key,
    normalize_problem_annotation,
    parse_question_array,
    validate_question_payload,
)

logger = logging.getLogger(__name__)

# 8 question types
QUESTION_TYPES = {
    "mc": "Multiple Choice — one correct answer from 4 options",
    "tf": "True/False — statement is true or false",
    "short_answer": "Short Answer — brief text response",
    "fill_blank": "Fill in the Blank — complete the sentence",
    "matching": "Matching — match items from two columns",
    "select_all": "Select All That Apply — multiple correct answers",
    "free_response": "Free Response — extended written answer",
    "coding": "Coding — write code to solve a problem (LLM-graded, no execution)",
}

EXTRACTION_PROMPT = """You are an expert educator creating practice questions from learning materials.

Given the content below, extract or generate practice questions. Follow these rules:

1. Generate a mix of question types: mc (multiple choice), tf (true/false), short_answer, fill_blank, and coding (for programming/technical content)
2. Each question should test understanding, not just recall
3. For multiple choice, always provide exactly 4 options (A, B, C, D)
4. Include the correct answer and a brief explanation
5. Generate 3-8 questions depending on content length and complexity
6. For EACH question, provide structured learning metadata:
   - difficulty_layer: 1 basic understanding, 2 standard application, 3 advanced/tricky transfer
   - core_concept: the main concept being tested
   - bloom_level: remember | understand | apply | analyze | evaluate | create
   - potential_traps: specific misconceptions or pitfalls (empty list if none)
   - layer_justification: one short reason for the difficulty_layer choice
   - skill_focus: what ability is being tested (for example recall, comparison, derivation, interpretation)
   - source_section: the section title if obvious from context

Output ONLY a valid JSON array with this structure:
```json
[
  {
    "question_type": "mc",
    "question": "What is the primary purpose of...?",
    "options": {"A": "Option 1", "B": "Option 2", "C": "Option 3", "D": "Option 4"},
    "correct_answer": "B",
    "explanation": "Option B is correct because...",
    "difficulty_layer": 2,
    "problem_metadata": {
      "core_concept": "main idea",
      "bloom_level": "apply",
      "potential_traps": ["common confusion 1"],
      "layer_justification": "Requires applying the idea to a new example",
      "skill_focus": "application",
      "source_section": "Section title"
    }
  },
  {
    "question_type": "tf",
    "question": "The process of X always results in Y.",
    "options": null,
    "correct_answer": "False",
    "explanation": "This is false because...",
    "difficulty_layer": 1,
    "problem_metadata": {
      "core_concept": "X versus Y",
      "bloom_level": "understand",
      "potential_traps": [],
      "layer_justification": "Direct comprehension check",
      "skill_focus": "concept check",
      "source_section": "Section title"
    }
  },
  {
    "question_type": "short_answer",
    "question": "Explain the difference between X and Y.",
    "options": null,
    "correct_answer": "X differs from Y in that...",
    "explanation": "The key distinction is...",
    "difficulty_layer": 2,
    "problem_metadata": {
      "core_concept": "difference between X and Y",
      "bloom_level": "analyze",
      "potential_traps": ["mixing the definitions"],
      "layer_justification": "Requires comparison rather than recall",
      "skill_focus": "comparison",
      "source_section": "Section title"
    }
  },
  {
    "question_type": "fill_blank",
    "question": "The _____ algorithm is used for finding shortest paths.",
    "options": null,
    "correct_answer": "Dijkstra's",
    "explanation": "Dijkstra's algorithm...",
    "difficulty_layer": 1,
    "problem_metadata": {
      "core_concept": "shortest path algorithms",
      "bloom_level": "remember",
      "potential_traps": [],
      "layer_justification": "Direct recall of a named algorithm",
      "skill_focus": "recall",
      "source_section": "Section title"
    }
  },
  {
    "question_type": "coding",
    "question": "Write a Python function that returns the factorial of n using recursion.",
    "options": null,
    "correct_answer": "def factorial(n):\n    if n <= 1:\n        return 1\n    return n * factorial(n - 1)",
    "explanation": "The recursive case multiplies n by factorial(n-1), with the base case returning 1 when n <= 1.",
    "difficulty_layer": 2,
    "problem_metadata": {
      "core_concept": "recursion",
      "bloom_level": "apply",
      "potential_traps": ["forgetting the base case", "not handling n=0"],
      "layer_justification": "Requires translating a mathematical definition into working code",
      "skill_focus": "implementation",
      "source_section": "Section title"
    }
  }
]
```

IMPORTANT: Output ONLY the JSON array, no other text."""

_REPAIR_PROMPT = """You are repairing ONE invalid practice question so it can be safely saved.

Return ONLY one valid JSON object using the shared schema:
{
  "question_type": "...",
  "question": "...",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."} | null,
  "correct_answer": "...",
  "explanation": "...",
  "difficulty_layer": 1 | 2 | 3,
  "problem_metadata": {
    "core_concept": "...",
    "bloom_level": "remember|understand|apply|analyze|evaluate|create",
    "potential_traps": [],
    "layer_justification": "...",
    "skill_focus": "...",
    "source_section": "..."
  }
}

Rules:
- Fix only the validation issues called out below.
- Keep the question grounded in the provided source excerpt.
- For `mc`, provide exactly 4 options and ensure `correct_answer` is one option label.
- For `tf`, use `True` or `False`.
- Always provide a non-empty `correct_answer` and `explanation`.
- Never add commentary outside the JSON object."""

_SHORT_CONTENT_THRESHOLD = 500
_MIN_VALID_QUESTIONS_SHORT = 1
_MIN_VALID_QUESTIONS_DEFAULT = 2
_MAX_NODE_ERRORS = 5
_QUESTION_TYPE_SHARE_CAP = 0.6
_QUESTION_TYPE_MIN_CAP = 2
_SIMILARITY_DUPLICATE_THRESHOLD = 0.85


@dataclass
class QuizNodeFailure:
    title: str
    reason: str
    node_id: str | None = None
    discarded_count: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "title": self.title,
            "reason": self.reason,
            "discarded_count": self.discarded_count,
            "errors": self.errors,
        }


@dataclass
class QuizExtractionOutcome:
    problems: list[PracticeProblem] = field(default_factory=list)
    validated_count: int = 0
    repaired_count: int = 0
    discarded_count: int = 0
    warnings: list[str] = field(default_factory=list)
    node_failures: list[QuizNodeFailure] = field(default_factory=list)

    def extend(self, other: "QuizExtractionOutcome") -> None:
        self.problems.extend(other.problems)
        self.validated_count += other.validated_count
        self.repaired_count += other.repaired_count
        self.discarded_count += other.discarded_count
        self.warnings.extend(other.warnings)
        self.node_failures.extend(other.node_failures)


@dataclass
class _PreparedQuestionBatch:
    questions: list[dict[str, Any]] = field(default_factory=list)
    repaired_count: int = 0
    discarded_count: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _normalize_problem_metadata(
    question: dict,
    *,
    title: str,
) -> tuple[int | None, dict]:
    normalized = normalize_problem_annotation(question, title=title, source="extracted")
    return normalized["difficulty_layer"], normalized["problem_metadata"]


_MODE_QUIZ_HINTS: dict[str, str] = {
    "exam_prep": "\n\nMode: EXAM PREP — Bias toward Layer 2-3 difficulty. Include time estimates per question. Prefer application and analysis questions.",
    "maintenance": "\n\nMode: MAINTENANCE — Only generate questions about previously-covered core concepts. Focus on retention and recall.",
    "self_paced": "\n\nMode: SELF-PACED — Include open-ended and cross-topic questions. Encourage deeper exploration.",
    "course_following": "\n\nMode: COURSE FOLLOWING — Strictly follow the provided content. Only test concepts explicitly covered in the material.",
}

_DIFFICULTY_HINTS: dict[str, str] = {
    "easy": "\n\nDifficulty: EASY — Mostly Layer 1-2 questions. Focus on core definitions and basic checks.",
    "medium": "\n\nDifficulty: MEDIUM — Balanced Layer 1-3 mix. Emphasize applied understanding.",
    "hard": "\n\nDifficulty: HARD — Bias strongly toward Layer 2-3. Include tricky distractors and transfer scenarios.",
}


def _minimum_valid_questions(content: str) -> int:
    if len(content.strip()) <= _SHORT_CONTENT_THRESHOLD:
        return _MIN_VALID_QUESTIONS_SHORT
    return _MIN_VALID_QUESTIONS_DEFAULT


def _question_token_set(text: str) -> set[str]:
    return {
        token
        for token in build_question_dedupe_key(text).split()
        if len(token) >= 3
    }


def _questions_are_too_similar(first: str, second: str) -> bool:
    first_tokens = _question_token_set(first)
    second_tokens = _question_token_set(second)
    if not first_tokens or not second_tokens:
        return False
    union = first_tokens | second_tokens
    if not union:
        return False
    overlap = len(first_tokens & second_tokens) / len(union)
    return overlap >= _SIMILARITY_DUPLICATE_THRESHOLD


def _enforce_type_balance(
    questions: list[dict[str, Any]],
    *,
    title: str,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    if len(questions) < 3:
        return questions, 0, []

    max_per_type = max(_QUESTION_TYPE_MIN_CAP, math.ceil(len(questions) * _QUESTION_TYPE_SHARE_CAP))
    type_counts: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    warnings: list[str] = []
    discarded = 0

    for question in questions:
        question_type = str(question.get("question_type") or "mc")
        if type_counts.get(question_type, 0) >= max_per_type:
            discarded += 1
            warnings.append(
                f"Dropped extra {question_type} question in {title} to keep the quiz batch diverse."
            )
            continue
        type_counts[question_type] = type_counts.get(question_type, 0) + 1
        kept.append(question)

    return kept, discarded, warnings


async def _repair_question(
    *,
    client: Any,
    question: dict[str, Any],
    title: str,
    content: str,
    errors: list[str],
) -> dict[str, Any] | None:
    source_excerpt = content[:3000]
    user_msg = (
        f"Title: {title}\n\n"
        f"Validation errors:\n- " + "\n- ".join(errors[:6]) + "\n\n"
        f"Source excerpt:\n{source_excerpt}\n\n"
        f"Invalid question JSON:\n{question}"
    )
    try:
        repaired_raw, _ = await client.chat(_REPAIR_PROMPT, user_msg)
    except (ConnectionError, TimeoutError, ValueError, RuntimeError) as exc:
        logger.warning("Quiz repair call failed for %s: %s", title, exc)
        return None

    repaired_questions = parse_question_array(repaired_raw)
    if repaired_questions:
        return repaired_questions[0]
    return None


async def _prepare_question_batch(
    *,
    questions: list[dict[str, Any]],
    title: str,
    content: str,
    client: Any,
    allow_repair: bool,
) -> _PreparedQuestionBatch:
    prepared = _PreparedQuestionBatch()
    seen_questions: set[str] = set()

    for question in questions:
        validation = validate_question_payload(question, title=title, source="extracted")
        normalized = validation.question
        errors = list(validation.errors)
        repaired = False

        if errors and allow_repair:
            repaired_question = await _repair_question(
                client=client,
                question=question,
                title=title,
                content=content,
                errors=errors,
            )
            if repaired_question is not None:
                repaired_validation = validate_question_payload(
                    repaired_question,
                    title=title,
                    source="extracted",
                )
                normalized = repaired_validation.question
                errors = list(repaired_validation.errors)
                repaired = len(errors) == 0

        if errors or normalized is None:
            prepared.discarded_count += 1
            prepared.errors.append("; ".join(errors[:3]) if errors else "question: validation failed")
            continue

        dedupe_key = build_question_dedupe_key(normalized["question"])
        if dedupe_key in seen_questions:
            prepared.discarded_count += 1
            prepared.warnings.append(f"Dropped duplicate question in {title}.")
            continue
        if any(
            existing.get("question_type") == normalized["question_type"]
            and _questions_are_too_similar(existing["question"], normalized["question"])
            for existing in prepared.questions
        ):
            prepared.discarded_count += 1
            prepared.warnings.append(f"Dropped near-duplicate question in {title}.")
            continue

        seen_questions.add(dedupe_key)
        prepared.questions.append(normalized)
        if repaired:
            prepared.repaired_count += 1

    prepared.questions, type_balance_discards, type_balance_warnings = _enforce_type_balance(
        prepared.questions,
        title=title,
    )
    prepared.discarded_count += type_balance_discards
    prepared.warnings.extend(type_balance_warnings)
    return prepared


async def prepare_generated_questions(
    *,
    raw_content: str,
    title: str,
) -> _PreparedQuestionBatch:
    """Validate a raw assistant quiz payload before saving a generated set."""
    questions = parse_question_array(raw_content)
    if not questions:
        return _PreparedQuestionBatch(errors=["payload: no valid question array found"])

    prepared = _PreparedQuestionBatch()
    seen_questions: set[str] = set()
    for question in questions:
        validation = validate_question_payload(question, title=title, source="generated")
        normalized = validation.question
        if validation.errors or normalized is None:
            prepared.discarded_count += 1
            prepared.errors.append("; ".join(validation.errors[:3]) if validation.errors else "question: validation failed")
            continue

        dedupe_key = build_question_dedupe_key(normalized["question"])
        if dedupe_key in seen_questions:
            prepared.discarded_count += 1
            prepared.warnings.append(f"Dropped duplicate generated question in {title}.")
            continue
        if any(
            existing.get("question_type") == normalized["question_type"]
            and _questions_are_too_similar(existing["question"], normalized["question"])
            for existing in prepared.questions
        ):
            prepared.discarded_count += 1
            prepared.warnings.append(f"Dropped near-duplicate generated question in {title}.")
            continue

        seen_questions.add(dedupe_key)
        prepared.questions.append(normalized)

    prepared.questions, type_balance_discards, type_balance_warnings = _enforce_type_balance(
        prepared.questions,
        title=title,
    )
    prepared.discarded_count += type_balance_discards
    prepared.warnings.extend(type_balance_warnings)
    return prepared


def _build_low_quality_failure(
    *,
    title: str,
    content_node_id: uuid.UUID | None,
    validated_count: int,
    required_count: int,
    discarded_count: int,
    errors: list[str],
) -> QuizNodeFailure:
    reason = (
        f"Only {validated_count} validated question(s) survived quality checks; "
        f"required at least {required_count} to save this node."
    )
    return QuizNodeFailure(
        node_id=str(content_node_id) if content_node_id else None,
        title=title,
        reason=reason,
        discarded_count=discarded_count,
        errors=errors[:_MAX_NODE_ERRORS],
    )


async def extract_questions(
    content: str,
    title: str,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
    mode: str | None = None,
    difficulty: str | None = None,
) -> QuizExtractionOutcome:
    """Extract practice questions from content using LLM.

    Args:
        content: Text content to generate questions from
        title: Section title for context
        course_id: Course UUID
        content_node_id: Optional reference to content tree node
        mode: Learning mode hint for question generation style

    Returns:
        QuizExtractionOutcome with validated PracticeProblem objects and stats.
    """
    client = get_llm_client()

    user_msg = f"## {title}\n\n{content}"
    if mode and mode in _MODE_QUIZ_HINTS:
        user_msg += _MODE_QUIZ_HINTS[mode]
    if difficulty and difficulty in _DIFFICULTY_HINTS:
        user_msg += _DIFFICULTY_HINTS[difficulty]

    response, _ = await client.chat(
        EXTRACTION_PROMPT,
        user_msg,
    )

    questions = parse_question_array(response)
    if not questions:
        return QuizExtractionOutcome(
            warnings=[f"No parsable quiz questions were returned for {title}."],
            node_failures=[
                QuizNodeFailure(
                    node_id=str(content_node_id) if content_node_id else None,
                    title=title,
                    reason="LLM output did not contain a valid question array.",
                ),
            ],
        )

    prepared = await _prepare_question_batch(
        questions=questions,
        title=title,
        content=content,
        client=client,
        allow_repair=True,
    )

    validated_count = len(prepared.questions)
    minimum_valid = _minimum_valid_questions(content)
    if validated_count < minimum_valid:
        return QuizExtractionOutcome(
            validated_count=validated_count,
            repaired_count=prepared.repaired_count,
            discarded_count=prepared.discarded_count + validated_count,
            warnings=[
                f"{title}: discarded low-confidence quiz batch after validation ({validated_count}/{minimum_valid} usable questions).",
                *prepared.warnings,
            ],
            node_failures=[
                _build_low_quality_failure(
                    title=title,
                    content_node_id=content_node_id,
                    validated_count=validated_count,
                    required_count=minimum_valid,
                    discarded_count=prepared.discarded_count + validated_count,
                    errors=prepared.errors,
                ),
            ],
        )

    problems: list[PracticeProblem] = []
    for i, question in enumerate(prepared.questions):
        problem = build_practice_problem(
            course_id=course_id,
            content_node_id=content_node_id,
            title=title,
            question=question,
            order_index=i,
            source="extracted",
        )
        problems.append(problem)

    return QuizExtractionOutcome(
        problems=problems,
        validated_count=validated_count,
        repaired_count=prepared.repaired_count,
        discarded_count=prepared.discarded_count,
        warnings=prepared.warnings,
    )


async def extract_all_questions(
    nodes: list[dict],
    course_id: uuid.UUID,
) -> list[PracticeProblem]:
    """Extract questions from all content tree nodes that have content."""
    all_problems = []
    for node in nodes:
        if node.get("content") and len(node["content"]) > 100:
            outcome = await extract_questions(
                node["content"],
                node["title"],
                course_id,
                content_node_id=node.get("id"),
            )
            all_problems.extend(outcome.problems)
    return all_problems
