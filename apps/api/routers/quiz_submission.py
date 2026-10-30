"""Quiz submission endpoints: submit answers, list problems."""

import logging
import uuid

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session, get_db
from models.course import Course
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from schemas.quiz import (
    AnswerResponse,
    ProblemResponse,
    SubmitAnswerRequest,
)
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.loom_flags import loom_enabled
from sqlalchemy.exc import SQLAlchemyError

from libs.exceptions import NotFoundError

router = APIRouter()


@router.get("/{course_id}", response_model=list[ProblemResponse], summary="List practice problems", description="Return paginated practice problems for a course, excluding diagnostics.")
async def list_problems(
    course_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user-facing practice problems for a course."""
    await get_course_or_404(db, course_id, user_id=user.id)

    result = await db.execute(
        select(PracticeProblem)
        .where(PracticeProblem.course_id == course_id)
        .where(PracticeProblem.is_diagnostic == False)
        .where(PracticeProblem.is_archived == False)
        .order_by(PracticeProblem.order_index)
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


async def _auto_derive_diagnostic(wrong_answer_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Background task: auto-generate a diagnostic pair for a wrong answer."""
    try:
        async with async_session() as db:
            from models.ingestion import WrongAnswer
            from models.practice import PracticeProblem as PP
            result = await db.execute(
                select(WrongAnswer, PP)
                .join(PP, WrongAnswer.problem_id == PP.id)
                .where(WrongAnswer.id == wrong_answer_id, WrongAnswer.user_id == user_id)
            )
            row = result.one_or_none()
            if not row:
                return
            wa, problem = row
            # Skip if diagnostic pair already exists
            existing = await db.execute(
                select(PP.id).where(PP.parent_problem_id == problem.id, PP.is_diagnostic == True)
            )
            if existing.scalar_one_or_none():
                return
            if problem.is_diagnostic or (problem.difficulty_layer and problem.difficulty_layer < 2):
                return

            from services.diagnosis.derive import derive_diagnostic
            await derive_diagnostic(db, wa, problem)
            await db.commit()
            logger.info("Auto-generated diagnostic pair for wrong answer %s", wrong_answer_id)
    except (SQLAlchemyError, ValueError, KeyError, TypeError):
        logger.exception("Auto-derive diagnostic failed (best-effort)")


async def _check_effective_review(
    problem_id: uuid.UUID, course_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Background: if user previously got this problem wrong, record effective_review signal."""
    try:
        async with async_session() as db:
            prev_wrong = await db.execute(
                select(PracticeResult.id).where(
                    PracticeResult.problem_id == problem_id,
                    PracticeResult.user_id == user_id,
                    PracticeResult.is_correct == False,  # noqa: E712
                ).limit(1)
            )
            if prev_wrong.scalar_one_or_none() is None:
                return  # No prior wrong answer — not an improvement
            from services.block_decision.preference import record_block_event
            await record_block_event(db, user_id, course_id, "review", "effective_review")
            await db.commit()
            logger.info("Recorded effective_review signal for problem %s", problem_id)
    except (SQLAlchemyError, ValueError, ImportError):
        logger.exception("Effective review check failed (best-effort)")


def _with_grading_detail(detail: dict | None, grade) -> dict | None:
    """Attach how the answer was graded (and why) to the wrong-answer record."""
    if grade.mode == "objective" and not grade.rationale:
        return detail
    merged = dict(detail or {})
    merged["grading"] = grade.to_dict()
    return merged


async def _auto_detect_confusion(course_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Background task: detect confusion pairs from accumulated wrong answers."""
    try:
        async with async_session() as db:
            from services.loom_confusion import detect_confusion_pairs
            await detect_confusion_pairs(db, course_id, user_id, min_occurrences=1)
            await db.commit()
    except (SQLAlchemyError, ValueError, KeyError):
        logger.exception("Auto confusion detection failed (best-effort)")


@router.post("/submit", response_model=AnswerResponse, summary="Submit a quiz answer", description="Grade a practice answer, classify errors, and update mastery tracking.")
async def submit_answer(
    body: SubmitAnswerRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit an answer to a practice problem."""
    result = await db.execute(
        select(PracticeProblem)
        .join(Course, PracticeProblem.course_id == Course.id)
        .where(
            PracticeProblem.id == body.problem_id,
            Course.user_id == user.id,
        )
    )
    problem = result.scalar_one_or_none()
    if not problem:
        raise NotFoundError("Problem", body.problem_id)

    warnings: list[str] = []

    from services.practice.grading import grade_answer

    grade = await grade_answer(problem, body.user_answer)
    is_correct = grade.is_correct
    warnings.extend(grade.warnings)

    pr = PracticeResult(
        problem_id=problem.id,
        user_id=user.id,
        user_answer=body.user_answer,
        is_correct=is_correct,
        ai_explanation=problem.explanation,
        difficulty_layer=problem.difficulty_layer,
        answer_time_ms=body.answer_time_ms,
    )

    error_category = None
    classification = None
    if not is_correct and problem.correct_answer:
        try:
            from services.diagnosis.classifier import classify_error
            classification = await classify_error(
                question=problem.question,
                correct_answer=problem.correct_answer,
                user_answer=body.user_answer,
                problem_metadata=problem.problem_metadata,
            )
            error_category = classification["category"]
            pr.error_category = error_category
        except (ValueError, KeyError, TypeError, OSError):
            logger.exception("Error classification failed (best-effort)")
            warnings.append("error_classification_failed")

    db.add(pr)

    wa = None
    if not is_correct:
        from models.ingestion import WrongAnswer
        wa = WrongAnswer(
            user_id=user.id,
            problem_id=problem.id,
            course_id=problem.course_id,
            user_answer=body.user_answer,
            correct_answer=problem.correct_answer,
            explanation=problem.explanation,
            error_category=error_category,
            error_detail=_with_grading_detail(classification if error_category else None, grade),
            knowledge_points=problem.knowledge_points,
        )
        db.add(wa)

    try:
        from services.progress.tracker import update_quiz_result
        await update_quiz_result(
            db, user.id, problem.course_id, problem.content_node_id,
            is_correct=is_correct,
            error_category=error_category,
            answer_time_ms=body.answer_time_ms,
        )
    except (SQLAlchemyError, ValueError, TypeError):
        logger.exception("Progress update failed (best-effort)")
        warnings.append("progress_update_failed")

    # Normalize knowledge_points to list[str] for consistent handling
    _kp = problem.knowledge_points
    kp_list: list[str] = (
        [str(x) for x in _kp] if isinstance(_kp, list)
        else [_kp] if isinstance(_kp, str)
        else []
    )

    # LOOM (experimental): apply the same attempt fact to the derived concept
    # ledger, using the node id resolved at ingestion when available.
    if loom_enabled() and kp_list:
        from services.loom_mastery import update_concept_mastery
        meta = problem.problem_metadata if isinstance(problem.problem_metadata, dict) else {}
        node_id: uuid.UUID | None = None
        try:
            node_id = uuid.UUID(str(meta["knowledge_node_id"])) if meta.get("knowledge_node_id") else None
        except ValueError:
            node_id = None
        try:
            if node_id is not None:
                await update_concept_mastery(
                    db, user.id, None, problem.course_id,
                    correct=is_correct, question_type=problem.question_type,
                    knowledge_node_id=node_id,
                )
            else:
                for kp in kp_list:
                    await update_concept_mastery(
                        db, user.id, str(kp), problem.course_id,
                        correct=is_correct, question_type=problem.question_type,
                    )
        except (SQLAlchemyError, ValueError, KeyError):
            logger.exception("Concept mastery update failed for %s", kp_list)
            warnings.append("concept_mastery_update_failed")

    # Emit analytics event before committing — single transaction for atomicity
    try:
        from services.analytics.events import emit_quiz_answered
        await emit_quiz_answered(
            db,
            user_id=user.id,
            course_id=problem.course_id,
            quiz_id=str(problem.id),
            score=1.0 if is_correct else 0.0,
            correct=is_correct,
            agent_name="quiz_router",
            answers={"user_answer": body.user_answer, "error_category": error_category},
        )
    except (SQLAlchemyError, ValueError, TypeError):
        logger.exception("Learning event emission failed (best-effort)")
        warnings.append("analytics_event_failed")

    await db.commit()

    if not is_correct and wa:
        background_tasks.add_task(_auto_derive_diagnostic, wa.id, user.id)
        # Auto-detect confusion pairs from accumulated wrong answers (LOOM only)
        if loom_enabled():
            background_tasks.add_task(_auto_detect_confusion, problem.course_id, user.id)

    # Detect improvement: correct answer on a previously-wrong problem → effective_review signal
    if is_correct:
        background_tasks.add_task(
            _check_effective_review, problem.id, problem.course_id, user.id
        )

    # Check prerequisite gaps on wrong answers
    prerequisite_gaps = None
    if loom_enabled() and not is_correct and kp_list:
        try:
            from services.loom_graph import check_prerequisite_gaps
            gaps = await check_prerequisite_gaps(
                db, user.id, problem.course_id,
                failed_concept_names=kp_list,
            )
            if gaps:
                prerequisite_gaps = gaps[:3]
        except (SQLAlchemyError, ValueError, KeyError):
            logger.exception("Prerequisite gap check failed (best-effort)")
            warnings.append("prerequisite_gap_check_failed")

    return AnswerResponse(
        is_correct=is_correct,
        correct_answer=problem.correct_answer,
        explanation=problem.explanation,
        grading_mode=grade.mode,
        grading_rationale=grade.rationale,
        prerequisite_gaps=prerequisite_gaps,
        warnings=warnings,
    )
