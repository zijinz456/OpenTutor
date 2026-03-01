"""Wrong answer management API — v3 error review system.

Endpoints for listing wrong answers, retrying, and generating derived questions.
"""

import json
import re
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.ingestion import WrongAnswer
from models.practice import PracticeProblem
from models.user import User
from services.auth.dependency import get_current_user
from libs.exceptions import NotFoundError
from services.practice.annotation import build_practice_problem

router = APIRouter()


# ── Schemas ──

class WrongAnswerResponse(BaseModel):
    id: uuid.UUID
    problem_id: uuid.UUID
    question: str | None = None
    question_type: str | None = None
    user_answer: str
    correct_answer: str | None
    explanation: str | None
    error_category: str | None
    diagnosis: str | None = None
    error_detail: dict | None = None
    knowledge_points: list | None
    review_count: int
    mastered: bool

    model_config = {"from_attributes": True}


class RetryRequest(BaseModel):
    user_answer: str


class RetryResponse(BaseModel):
    is_correct: bool
    correct_answer: str | None
    explanation: str | None


_DERIVE_FALLBACK = {"question": "", "options": None, "correct_answer": None, "explanation": None}


def _extract_json_object(text: str) -> dict:
    """Extract the first balanced JSON object from mixed LLM output.

    Uses brace-depth counting instead of a greedy regex to handle nested objects.
    """
    start = text.find("{")
    if start == -1:
        return {**_DERIVE_FALLBACK, "question": text}
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
                # Keep looking for the next object
    return {**_DERIVE_FALLBACK, "question": text}


# ── Endpoints ──

@router.get("/{course_id}", response_model=list[WrongAnswerResponse])
async def list_wrong_answers(
    course_id: uuid.UUID,
    mastered: bool | None = None,
    error_category: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List wrong answers for a course, optionally filtered."""
    query = (
        select(WrongAnswer, PracticeProblem)
        .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
        .where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
        )
        .order_by(WrongAnswer.created_at.desc())
    )

    if mastered is not None:
        query = query.where(WrongAnswer.mastered == mastered)
    if error_category:
        query = query.where(WrongAnswer.error_category == error_category)

    result = await db.execute(query)
    rows = result.all()

    return [
        WrongAnswerResponse(
            id=wa.id,
            problem_id=wa.problem_id,
            question=prob.question,
            question_type=prob.question_type,
            user_answer=wa.user_answer,
            correct_answer=wa.correct_answer,
            explanation=wa.explanation,
            error_category=wa.error_category,
            diagnosis=wa.diagnosis,
            error_detail=wa.error_detail,
            knowledge_points=wa.knowledge_points,
            review_count=wa.review_count,
            mastered=wa.mastered,
        )
        for wa, prob in rows
    ]


@router.post("/{wrong_answer_id}/retry", response_model=RetryResponse)
async def retry_wrong_answer(
    wrong_answer_id: uuid.UUID,
    body: RetryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retry a wrong answer. Updates review count and mastery status."""
    result = await db.execute(
        select(WrongAnswer).where(
            WrongAnswer.id == wrong_answer_id,
            WrongAnswer.user_id == user.id,
        )
    )
    wa = result.scalar_one_or_none()
    if not wa:
        raise NotFoundError("Wrong answer")

    is_correct = False
    if wa.correct_answer:
        is_correct = body.user_answer.strip().lower() == wa.correct_answer.strip().lower()

    wa.review_count += 1
    wa.last_reviewed_at = func.now()
    if is_correct:
        wa.mastered = True

    await db.commit()

    return RetryResponse(
        is_correct=is_correct,
        correct_answer=wa.correct_answer,
        explanation=wa.explanation,
    )


@router.post("/{wrong_answer_id}/derive")
async def derive_question(
    wrong_answer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a diagnostic pair: a simplified "clean" version of the wrong question.

    VCE-inspired contrastive diagnosis: compare student performance on original
    vs simplified version to determine error root cause (concept gap vs trap
    vulnerability vs carelessness). The simplified version removes all
    distractors/traps while preserving the core concept.

    The result includes `simplifications_made` and `core_concept_preserved`
    fields for auditability (VCE annotation pattern).
    """
    result = await db.execute(
        select(WrongAnswer, PracticeProblem)
        .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
        .where(
            WrongAnswer.id == wrong_answer_id,
            WrongAnswer.user_id == user.id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise NotFoundError("Wrong answer")

    wa, problem = row

    existing_diag_result = await db.execute(
        select(PracticeProblem)
        .where(
            PracticeProblem.parent_problem_id == problem.id,
            PracticeProblem.is_diagnostic == True,
        )
        .order_by(PracticeProblem.created_at.desc())
    )
    for existing in existing_diag_result.scalars().all():
        metadata = existing.problem_metadata or {}
        if metadata.get("wrong_answer_id") == str(wa.id):
            return {
                "problem_id": str(existing.id),
                "original_problem_id": str(problem.id),
                "question": existing.question,
                "question_type": existing.question_type,
                "options": existing.options,
                "is_diagnostic": True,
                "simplifications_made": metadata.get("simplifications_made", []),
                "core_concept_preserved": metadata.get("core_concept_preserved", ""),
            }

    # Build metadata context for grounding (VCE pattern)
    metadata_str = ""
    if problem.problem_metadata:
        meta = problem.problem_metadata
        parts = []
        if meta.get("core_concept"):
            parts.append(f"Core concept: {meta['core_concept']}")
        if meta.get("potential_traps"):
            parts.append(f"Known traps to remove: {', '.join(meta['potential_traps'])}")
        if meta.get("bloom_level"):
            parts.append(f"Bloom's level: {meta['bloom_level']}")
        if parts:
            metadata_str = "\nQuestion metadata (use to guide simplification):\n" + "\n".join(parts)

    from services.llm.router import get_llm_client

    client = get_llm_client()
    prompt = f"""You are a diagnostic question designer. A student got this question wrong.
Generate a SIMPLIFIED "clean" diagnostic version that:
1. Tests the EXACT SAME core concept
2. Removes all distractors, traps, and misleading wording
3. Uses simpler numbers/context
4. If multi-step, only keep the key step

Original question: {problem.question}
Question type: {problem.question_type}
Correct answer: {wa.correct_answer}
Student's wrong answer: {wa.user_answer}
Error category: {wa.error_category or 'unknown'}
{metadata_str}

Return JSON only:
{{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}} or null, "correct_answer": "...", "explanation": "...", "simplifications_made": ["list of specific simplifications"], "core_concept_preserved": "name of the core concept being tested"}}"""

    response, _ = await client.chat(
        "You design diagnostic questions. Output valid JSON only.",
        prompt,
    )

    try:
        derived = json.loads(response)
    except json.JSONDecodeError:
        derived = _extract_json_object(response)

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

    # Save as diagnostic practice problem (linked to original)
    extra_metadata = {
        "simplifications_made": derived.get("simplifications_made", []),
        "core_concept_preserved": derived.get("core_concept_preserved", ""),
        "original_problem_id": str(problem.id),
        "wrong_answer_id": str(wa.id),
    }
    new_problem = build_practice_problem(
        course_id=problem.course_id,
        content_node_id=problem.content_node_id,
        title=problem.problem_metadata.get("core_concept") if problem.problem_metadata else (problem.question[:80] or "Diagnostic question"),
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
    await db.commit()
    await db.refresh(new_problem)

    return {
        "problem_id": str(new_problem.id),
        "original_problem_id": str(problem.id),
        "question": new_problem.question,
        "question_type": new_problem.question_type,
        "options": new_problem.options,
        "correct_answer": new_problem.correct_answer,
        "explanation": new_problem.explanation,
        "is_diagnostic": True,
        "simplifications_made": derived.get("simplifications_made", []),
        "core_concept_preserved": derived.get("core_concept_preserved", ""),
    }


@router.post("/{wrong_answer_id}/diagnose")
async def diagnose_from_pair(
    wrong_answer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Diagnose error type from a completed diagnostic pair.

    Reads the student's results on both original and simplified version,
    then applies the VCE contrastive diagnosis matrix:
    - Both wrong → fundamental_gap (concept not understood)
    - Clean right, original wrong → trap_vulnerability (concept OK, falls for traps)
    - Clean wrong, original right → carelessness (overthinking simple version)
    - Both right → mastered

    The diagnosis is stored on WrongAnswer.diagnosis as immutable annotation.
    """
    # Get the wrong answer and its diagnostic pair
    wa_result = await db.execute(
        select(WrongAnswer).where(
            WrongAnswer.id == wrong_answer_id,
            WrongAnswer.user_id == user.id,
        )
    )
    wa = wa_result.scalar_one_or_none()
    if not wa:
        raise NotFoundError("Wrong answer")

    if wa.diagnosis:
        return {
            "diagnosis": wa.diagnosis,
            "original_correct": wa.mastered,
            "clean_correct": None,
            "interpretation": "Existing diagnosis reused.",
        }

    # Find the diagnostic problem (clean version linked to original)
    diag_result = await db.execute(
        select(PracticeProblem).where(
            PracticeProblem.parent_problem_id == wa.problem_id,
            PracticeProblem.is_diagnostic == True,
        )
    )
    diag_problem = diag_result.scalar_one_or_none()
    if not diag_problem:
        raise NotFoundError("Diagnostic pair")

    # Check if student has attempted both
    from models.practice import PracticeResult

    # Original item may later become correct if the student retries and masters it.
    original_correct = wa.mastered

    # Clean version attempt
    clean_result = await db.execute(
        select(PracticeResult).where(
            PracticeResult.problem_id == diag_problem.id,
            PracticeResult.user_id == user.id,
        ).order_by(PracticeResult.answered_at.desc()).limit(1)
    )
    clean_attempt = clean_result.scalar_one_or_none()
    if not clean_attempt:
        return {
            "status": "pending",
            "message": "Student has not attempted the diagnostic (clean) version yet.",
            "diagnostic_problem_id": str(diag_problem.id),
        }

    clean_correct = clean_attempt.is_correct

    # VCE contrastive diagnosis matrix
    if not clean_correct and not original_correct:
        diagnosis = "fundamental_gap"
    elif clean_correct and not original_correct:
        diagnosis = "trap_vulnerability"
    elif not clean_correct and original_correct:
        diagnosis = "carelessness"
    else:
        diagnosis = "mastered"

    # Store diagnosis as immutable annotation
    wa.diagnosis = diagnosis
    wa.error_detail = {
        **(wa.error_detail or {}),
        "diagnosis": diagnosis,
        "original_correct": original_correct,
        "clean_correct": clean_correct,
        "diagnostic_problem_id": str(diag_problem.id),
    }
    await db.commit()

    return {
        "diagnosis": diagnosis,
        "original_correct": original_correct,
        "clean_correct": clean_correct,
        "interpretation": {
            "fundamental_gap": "Student cannot solve even the simplified version — core concept not understood.",
            "trap_vulnerability": "Student solves the clean version but fails the original — falls for traps/distractors.",
            "carelessness": "Student fails the simpler version but got the harder one — likely overthinking or careless.",
            "mastered": "Student now solves both versions — concept mastered.",
        }.get(diagnosis, ""),
    }


@router.get("/{course_id}/stats")
async def wrong_answer_stats(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get wrong answer statistics for a course."""
    # Total wrong answers
    total_result = await db.execute(
        select(func.count(WrongAnswer.id)).where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
        )
    )
    total = total_result.scalar() or 0

    # Mastered count
    mastered_result = await db.execute(
        select(func.count(WrongAnswer.id)).where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
            WrongAnswer.mastered == True,
        )
    )
    mastered = mastered_result.scalar() or 0

    # By error category
    category_result = await db.execute(
        select(WrongAnswer.error_category, func.count(WrongAnswer.id))
        .where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
        )
        .group_by(WrongAnswer.error_category)
    )
    by_category = {cat or "uncategorized": count for cat, count in category_result.all()}

    diagnosis_result = await db.execute(
        select(WrongAnswer.diagnosis, func.count(WrongAnswer.id))
        .where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
            WrongAnswer.diagnosis.isnot(None),
        )
        .group_by(WrongAnswer.diagnosis)
    )
    by_diagnosis = {diagnosis: count for diagnosis, count in diagnosis_result.all() if diagnosis}

    return {
        "total": total,
        "mastered": mastered,
        "unmastered": total - mastered,
        "by_category": by_category,
        "by_diagnosis": by_diagnosis,
    }
