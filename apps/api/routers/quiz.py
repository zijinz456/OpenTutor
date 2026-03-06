"""Quiz endpoints: extract questions, list problems, submit answers, and save generated sets."""

import logging
import uuid

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session, get_db
from models.content import CourseContentTree
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from schemas.quiz import (
    AnswerResponse,
    ExtractRequest,
    MasterySnapshotResponse,
    ProblemResponse,
    SaveGeneratedRequest,
    SubmitAnswerRequest,
)
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.llm.readiness import ensure_llm_ready
from services.parser.quiz import extract_questions
from services.practice.annotation import build_practice_problem, parse_question_array
from libs.exceptions import (
    NotFoundError,
    ValidationError,
    reraise_as_app_error,
)

router = APIRouter()


@router.get("/{course_id}/generated-batches")
async def list_generated_batches(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await get_course_or_404(db, course_id, user_id=user.id)

    result = await db.execute(
        select(PracticeProblem)
        .where(
            PracticeProblem.course_id == course_id,
            PracticeProblem.source == "generated",
            PracticeProblem.source_batch_id.isnot(None),
        )
        .order_by(PracticeProblem.source_batch_id, PracticeProblem.source_version.desc(), PracticeProblem.created_at.desc())
    )
    problems = result.scalars().all()
    batches: dict[str, dict] = {}
    for problem in problems:
        batch_id = str(problem.source_batch_id)
        batch = batches.get(batch_id)
        if not batch:
            metadata = problem.problem_metadata or {}
            batches[batch_id] = {
                "batch_id": batch_id,
                "title": metadata.get("source_section") or course.name,
                "current_version": problem.source_version,
                "problem_count": 0,
                "is_active": not problem.is_archived,
                "updated_at": problem.created_at.isoformat() if problem.created_at else None,
            }
            batch = batches[batch_id]
        if problem.source_version == batch["current_version"]:
            batch["problem_count"] += 1
            batch["is_active"] = batch["is_active"] or (not problem.is_archived)

    return sorted(batches.values(), key=lambda item: (item["is_active"], item["updated_at"] or ""), reverse=True)


@router.post("/save-generated")
async def save_generated_quiz(
    body: SaveGeneratedRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist an AI-generated practice set into the course question bank."""
    course = await get_course_or_404(db, body.course_id, user_id=user.id)

    questions = parse_question_array(body.raw_content)
    if not questions:
        raise ValidationError("No valid question set found in assistant response")

    replace_batch_id = body.replace_batch_id
    next_version = 1
    if replace_batch_id:
        prior_result = await db.execute(
            select(PracticeProblem).where(
                PracticeProblem.course_id == body.course_id,
                PracticeProblem.source == "generated",
                PracticeProblem.source_batch_id == replace_batch_id,
                PracticeProblem.is_archived == False,
            )
        )
        prior_problems = prior_result.scalars().all()
        if not prior_problems:
            raise NotFoundError("Generated batch")
        next_version = max(problem.source_version for problem in prior_problems) + 1
        for problem in prior_problems:
            problem.is_archived = True
    else:
        replace_batch_id = uuid.uuid4()

    max_order_result = await db.execute(
        select(func.max(PracticeProblem.order_index)).where(
            PracticeProblem.course_id == body.course_id,
            PracticeProblem.is_diagnostic == False,
            PracticeProblem.is_archived == False,
        )
    )
    start_order = (max_order_result.scalar() or 0) + 1
    title = body.title or course.name

    created: list[PracticeProblem] = []
    for index, question in enumerate(questions):
        problem = build_practice_problem(
            course_id=body.course_id,
            content_node_id=None,
            title=title,
            question=question,
            order_index=start_order + index,
            source="generated",
            source_batch_id=replace_batch_id,
            source_version=next_version,
        )
        db.add(problem)
        created.append(problem)

    await db.commit()
    return {
        "saved": len(created),
        "problem_ids": [str(problem.id) for problem in created],
        "batch_id": str(replace_batch_id),
        "version": next_version,
        "replaced": bool(body.replace_batch_id),
    }


@router.post("/extract")
async def extract_quiz(body: ExtractRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Extract questions from a content node or all nodes in a course."""
    await get_course_or_404(db, body.course_id, user_id=user.id)
    await ensure_llm_ready("Quiz generation")

    try:
        if body.content_node_id:
            result = await db.execute(
                select(CourseContentTree).where(CourseContentTree.id == body.content_node_id)
            )
            node = result.scalar_one_or_none()
            if not node or not node.content:
                raise NotFoundError("Content node not found or empty")

            problems = await extract_questions(
                node.content, node.title, body.course_id, body.content_node_id
            )
        else:
            import asyncio

            target_count = body.count or 10
            # Process a reasonable number of nodes — ~2 questions per node
            max_nodes = min(max(target_count // 2, 3), 15)

            result = await db.execute(
                select(CourseContentTree)
                .where(CourseContentTree.course_id == body.course_id)
                .where(CourseContentTree.content.isnot(None))
            )
            nodes = result.scalars().all()
            eligible = [n for n in nodes if n.content and len(n.content) > 100][:max_nodes]

            sem = asyncio.Semaphore(3)

            async def _extract(n):
                async with sem:
                    try:
                        return await asyncio.wait_for(
                            extract_questions(n.content, n.title, body.course_id, n.id),
                            timeout=60,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Quiz extraction timed out for node %s", n.title)
                        return []

            results = await asyncio.gather(*[_extract(n) for n in eligible], return_exceptions=True)
            problems = []
            failures = []
            for r in results:
                if isinstance(r, list):
                    problems.extend(r)
                elif isinstance(r, Exception):
                    failures.append(r)
            if failures and not problems:
                raise failures[0]
            if failures:
                logger.warning(
                    "Quiz extraction skipped %d/%d node(s) due to errors",
                    len(failures),
                    len(results),
                )
    except Exception as exc:
        reraise_as_app_error(exc, "Quiz extraction failed")

    for p in problems:
        db.add(p)
    await db.commit()

    return {"status": "ok", "problems_created": len(problems)}


@router.get("/{course_id}", response_model=list[ProblemResponse])
async def list_problems(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List user-facing practice problems for a course."""
    result = await db.execute(
        select(PracticeProblem)
        .where(PracticeProblem.course_id == course_id)
        .where(PracticeProblem.is_diagnostic == False)
        .where(PracticeProblem.is_archived == False)
        .order_by(PracticeProblem.order_index)
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
    except Exception as e:
        logger.warning("Auto-derive diagnostic failed (best-effort): %s", e)


@router.post("/submit", response_model=AnswerResponse)
async def submit_answer(
    body: SubmitAnswerRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit an answer to a practice problem."""
    result = await db.execute(
        select(PracticeProblem).where(PracticeProblem.id == body.problem_id)
    )
    problem = result.scalar_one_or_none()
    if not problem:
        raise NotFoundError("Problem", body.problem_id)

    is_correct = False
    if problem.correct_answer:
        is_correct = body.user_answer.strip().lower() == problem.correct_answer.strip().lower()

    pr = PracticeResult(
        problem_id=problem.id,
        user_id=user.id,
        user_answer=body.user_answer,
        is_correct=is_correct,
        ai_explanation=problem.explanation,
        difficulty_layer=problem.difficulty_layer,
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
        except Exception as e:
            logger.warning("Error classification failed (best-effort): %s", e)

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
            error_detail=classification if error_category else None,
            knowledge_points=problem.knowledge_points,
        )
        db.add(wa)

    try:
        from services.progress.tracker import update_quiz_result
        await update_quiz_result(
            db, user.id, problem.course_id, problem.content_node_id,
            is_correct=is_correct,
            error_category=error_category,
        )
    except Exception as e:
        logger.warning("Progress update failed (best-effort): %s", e)

    # Experiment system removed in Phase 1.3

    await db.commit()

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
        await db.commit()
    except Exception:
        logger.debug("Learning event emission failed (best-effort)")

    if not is_correct and wa:
        background_tasks.add_task(_auto_derive_diagnostic, wa.id, user.id)

    return AnswerResponse(
        is_correct=is_correct,
        correct_answer=problem.correct_answer,
        explanation=problem.explanation,
    )


# ── Phase 4: Mastery history time-series endpoint ──


@router.get("/{course_id}/mastery-history", response_model=list[MasterySnapshotResponse])
async def mastery_history(
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return mastery score time-series for analytics charts."""
    from models.mastery_snapshot import MasterySnapshot

    await get_course_or_404(db, course_id, user.id)

    query = (
        select(MasterySnapshot)
        .where(
            MasterySnapshot.user_id == user.id,
            MasterySnapshot.course_id == course_id,
        )
        .order_by(MasterySnapshot.recorded_at.desc())
        .limit(limit)
    )
    if content_node_id:
        query = query.where(MasterySnapshot.content_node_id == content_node_id)

    result = await db.execute(query)
    snapshots = result.scalars().all()

    return [
        MasterySnapshotResponse(
            mastery_score=s.mastery_score,
            gap_type=s.gap_type,
            content_node_id=str(s.content_node_id) if s.content_node_id else None,
            recorded_at=s.recorded_at.isoformat(),
        )
        for s in reversed(snapshots)
    ]
