"""Answer grading for practice problems.

Two tiers:

1. Objective grading (no LLM) — multiple choice, true/false, select-all,
   numeric answers and short fill-in-the-blank answers with an answer key.
   Comparison is tolerant of case, whitespace, punctuation, option label vs
   option text, and locale spellings of true/false. Each problem can carry
   ``problem_metadata.accepted_answers`` with extra correct spellings.

2. Semantic grading (LLM) — only for free-text types (short_answer,
   free_response, and fill_blank when the objective check fails). The LLM
   verdict is returned together with its rationale so the caller can persist
   the reason next to the attempt instead of a bare boolean.

``grade_answer`` never raises on LLM failure: it reports ``mode="unavailable"``
and leaves ``is_correct`` False with a warning the caller can surface.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

OBJECTIVE_TYPES = {"mc", "tf", "select_all", "matching"}
TEXT_TYPES = {"short_answer", "free_response", "fill_blank"}

_TRUE_WORDS = {"true", "t", "yes", "y", "correct", "对", "正确", "是", "真"}
_FALSE_WORDS = {"false", "f", "no", "n", "incorrect", "错", "错误", "否", "假"}

_NUMBER_RE = re.compile(r"^[-+]?(\d+(\.\d+)?|\.\d+)(e[-+]?\d+)?$", re.IGNORECASE)


@dataclass
class GradeResult:
    is_correct: bool
    mode: str  # "objective" | "llm" | "unavailable"
    rationale: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"is_correct": self.is_correct, "mode": self.mode, "rationale": self.rationale}


def normalize_text(value: Any) -> str:
    """Lowercase, NFKC-normalize, strip punctuation and collapse whitespace."""
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = re.sub(r"[\s　]+", " ", text)
    text = re.sub(r"[^\w\s.%/-]", "", text)
    text = text.replace(" .", ".").strip(" .")
    return text


def _parse_number(text: str) -> float | None:
    cleaned = text.replace(",", "").replace(" ", "")
    pct = cleaned.endswith("%")
    if pct:
        cleaned = cleaned[:-1]
    if not _NUMBER_RE.match(cleaned):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value / 100 if pct else value


def _numbers_equal(a: str, b: str) -> bool | None:
    na, nb = _parse_number(a), _parse_number(b)
    if na is None or nb is None:
        return None
    return abs(na - nb) <= max(1e-9, 1e-6 * max(abs(na), abs(nb)))


def _split_labels(value: str) -> set[str]:
    return {part.strip().upper() for part in re.split(r"[,/;|\s]+", value or "") if part.strip()}


def _answer_candidates(problem) -> list[str]:
    """Correct answer plus any alternative spellings stored on the problem."""
    candidates: list[str] = []
    if problem.correct_answer:
        candidates.append(str(problem.correct_answer))
    metadata = problem.problem_metadata if isinstance(problem.problem_metadata, dict) else {}
    extra = metadata.get("accepted_answers")
    if isinstance(extra, list):
        candidates.extend(str(item) for item in extra if str(item).strip())
    elif isinstance(extra, str) and extra.strip():
        candidates.append(extra)
    return candidates


def _option_label_for(problem, user_answer: str) -> str | None:
    """Map an answer given as option text (or 'B. text') back to its label."""
    options = problem.options if isinstance(problem.options, dict) else {}
    if not options:
        return None
    norm = normalize_text(user_answer)
    for label, text in options.items():
        label_u = str(label).strip().upper()
        if norm == label_u.lower():
            return label_u
        text_norm = normalize_text(text)
        if norm == text_norm or norm == f"{label_u.lower()} {text_norm}" or norm == f"{label_u.lower()}. {text_norm}":
            return label_u
    return None


def grade_objective(problem, user_answer: str) -> bool | None:
    """Deterministic grading. Returns None when the type needs semantic grading."""
    qtype = (problem.question_type or "").lower()
    answer = (user_answer or "").strip()
    if not answer or not problem.correct_answer:
        return False if qtype in OBJECTIVE_TYPES else None

    if qtype == "mc":
        correct = str(problem.correct_answer).strip()
        # The key may be stored as a label ("B") or as the option text ("Paris").
        expected = _option_label_for(problem, correct) or correct.upper().rstrip(".)")
        given = _option_label_for(problem, answer) or answer.upper().rstrip(".)")
        return given == expected or normalize_text(answer) == normalize_text(correct)

    if qtype == "tf":
        norm = normalize_text(answer)
        expected = normalize_text(problem.correct_answer)
        if norm in _TRUE_WORDS:
            return expected in _TRUE_WORDS
        if norm in _FALSE_WORDS:
            return expected in _FALSE_WORDS
        return norm == expected

    if qtype == "select_all":
        given = set()
        for part in re.split(r"[,/;|]+", answer):
            part = part.strip()
            if not part:
                continue
            label = _option_label_for(problem, part)
            given.add(label or part.upper())
        return given == _split_labels(str(problem.correct_answer))

    if qtype == "matching":
        return normalize_text(answer) == normalize_text(problem.correct_answer)

    # Text types: exact/alternative/numeric match counts as correct without an LLM.
    norm = normalize_text(answer)
    for candidate in _answer_candidates(problem):
        cand_norm = normalize_text(candidate)
        if norm and norm == cand_norm:
            return True
        numeric = _numbers_equal(answer, candidate)
        if numeric:
            return True
    return None


_TEXT_GRADING_PROMPT = """You are grading a student's short written answer against a reference answer.

Rules:
- Judge meaning, not wording. Paraphrases, synonyms and a different language are fine.
- The answer must contain the key idea(s) of the reference; extra correct detail is fine.
- Partial or vague answers that miss the key idea are incorrect.
- Respond with ONLY a JSON object: {"is_correct": true/false, "rationale": "one sentence"}"""


async def grade_text_answer(*, question: str, reference_answer: str, user_answer: str) -> GradeResult:
    """Semantic grading of free-text answers. Never raises."""
    if not user_answer.strip():
        return GradeResult(False, "objective", "No answer submitted.")

    try:
        from services.llm.router import get_llm_client
        from libs.text_utils import parse_llm_json

        client = get_llm_client("fast")
        raw, _ = await client.chat(
            _TEXT_GRADING_PROMPT,
            f"Question: {question}\n\nReference answer: {reference_answer}\n\nStudent answer: {user_answer}",
        )
        parsed = parse_llm_json(raw)
    except Exception as exc:  # noqa: BLE001 — provider SDKs raise their own hierarchies; grading must never raise
        logger.warning("Text grading LLM call failed: %s", exc)
        return GradeResult(False, "unavailable", None, ["text_grading_unavailable"])

    if not isinstance(parsed, dict) or "is_correct" not in parsed:
        return GradeResult(False, "unavailable", None, ["text_grading_parse_error"])
    return GradeResult(bool(parsed.get("is_correct")), "llm", str(parsed.get("rationale") or "").strip() or None)


async def grade_answer(problem, user_answer: str) -> GradeResult:
    """Grade an answer for any supported question type."""
    qtype = (problem.question_type or "").lower()

    if qtype == "coding":
        try:
            from services.diagnosis.coding_grader import grade_coding_answer

            result = await grade_coding_answer(
                question=problem.question,
                reference_answer=problem.correct_answer or "",
                user_code=user_answer,
            )
        except Exception:  # noqa: BLE001 — see grade_text_answer
            logger.exception("Coding grading failed (best-effort)")
            return GradeResult(False, "unavailable", None, ["coding_grading_failed"])
        return GradeResult(bool(result.get("is_correct")), "llm", result.get("feedback") or None)

    objective = grade_objective(problem, user_answer)
    if objective is not None:
        return GradeResult(objective, "objective")

    if qtype in TEXT_TYPES and problem.correct_answer:
        return await grade_text_answer(
            question=problem.question,
            reference_answer=problem.correct_answer,
            user_answer=user_answer,
        )

    return GradeResult(False, "objective", None, ["no_answer_key"])
