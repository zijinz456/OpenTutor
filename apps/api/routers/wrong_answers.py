"""Wrong answer management API — v3 error review system.

Endpoints for listing wrong answers, retrying, and generating derived questions.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.ingestion import WrongAnswer
from models.practice import PracticeProblem
from models.user import User
from schemas.wrong_answer import (
    DeriveResponse,
    DiagnoseResponse,
    RetryRequest,
    RetryResponse,
    WrongAnswerResponse,
    WrongAnswerStatsResponse,
)
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.diagnosis.derive import derive_diagnostic
from libs.exceptions import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Endpoints ──

@router.get("/{course_id}", response_model=list[WrongAnswerResponse])
async def list_wrong_answers(
    course_id: uuid.UUID,
    mastered: bool | None = None,
    error_category: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List wrong answers for a course, optionally filtered."""
    await get_course_or_404(db, course_id, user_id=user.id)
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

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.all()

    return [
        WrongAnswerResponse(
            id=wa.id,
            problem_id=wa.problem_id,
            question=prob.question,
            question_type=prob.question_type,
            options=prob.options,
            user_answer=wa.user_answer,
            correct_answer=wa.correct_answer,
            explanation=wa.explanation,
            error_category=wa.error_category,
            diagnosis=wa.diagnosis,
            error_detail=wa.error_detail,
            knowledge_points=wa.knowledge_points,
            review_count=wa.review_count,
            mastered=wa.mastered,
            created_at=wa.created_at,
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


@router.post("/{wrong_answer_id}/derive", response_model=DeriveResponse)
async def derive_question(
    wrong_answer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a diagnostic pair: a simplified "clean" version of the wrong question."""
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

    # Check for existing diagnostic pair first
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

    new_problem = await derive_diagnostic(db, wa, problem)
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
        "simplifications_made": (new_problem.problem_metadata or {}).get("simplifications_made", []),
        "core_concept_preserved": (new_problem.problem_metadata or {}).get("core_concept_preserved", ""),
    }


@router.post("/{wrong_answer_id}/diagnose", response_model=DiagnoseResponse)
async def diagnose_from_pair(
    wrong_answer_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Diagnose error type from a completed diagnostic pair.

    VCE contrastive diagnosis matrix:
    - Both wrong → fundamental_gap
    - Clean right, original wrong → trap_vulnerability
    - Clean wrong, original right → carelessness
    - Both right → mastered
    """
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

    diag_result = await db.execute(
        select(PracticeProblem).where(
            PracticeProblem.parent_problem_id == wa.problem_id,
            PracticeProblem.is_diagnostic == True,
        )
    )
    diag_problem = diag_result.scalar_one_or_none()
    if not diag_problem:
        raise NotFoundError("Diagnostic pair")

    from models.practice import PracticeResult

    original_correct = wa.mastered

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

    if not clean_correct and not original_correct:
        diagnosis = "fundamental_gap"
    elif clean_correct and not original_correct:
        diagnosis = "trap_vulnerability"
    elif not clean_correct and original_correct:
        diagnosis = "carelessness"
    else:
        diagnosis = "mastered"

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


@router.get("/{course_id}/stats", response_model=WrongAnswerStatsResponse)
async def wrong_answer_stats(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get wrong answer statistics for a course."""
    await get_course_or_404(db, course_id, user_id=user.id)
    total_result = await db.execute(
        select(func.count(WrongAnswer.id)).where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
        )
    )
    total = total_result.scalar() or 0

    mastered_result = await db.execute(
        select(func.count(WrongAnswer.id)).where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
            WrongAnswer.mastered == True,
        )
    )
    mastered = mastered_result.scalar() or 0

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
