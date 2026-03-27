"""Quiz generation endpoints: extract questions and save generated sets."""

import logging
import uuid

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.content import CourseContentTree, INFO_CATEGORIES
from models.practice import PracticeProblem
from models.user import User
from schemas.quiz import (
    ExtractRequest,
    ExtractResponse,
    PretestAnswerRequest,
    PretestStartRequest,
    SaveGeneratedRequest,
)
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.llm.readiness import ensure_llm_ready
from services.parser.quiz import QuizExtractionOutcome, QuizNodeFailure, extract_questions, prepare_generated_questions
from services.practice.annotation import build_practice_problem
from sqlalchemy.exc import SQLAlchemyError

from libs.exceptions import (
    NotFoundError,
    ValidationError,
    reraise_as_app_error,
)

router = APIRouter()


@router.get("/{course_id}/generated-batches", summary="List generated quiz batches", description="Return all AI-generated quiz batches for a course with version info.")
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


@router.post("/save-generated", summary="Save generated quiz", description="Persist an AI-generated practice set into the course question bank.")
async def save_generated_quiz(
    body: SaveGeneratedRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist an AI-generated practice set into the course question bank."""
    course = await get_course_or_404(db, body.course_id, user_id=user.id)
    title = body.title or course.name

    prepared = await prepare_generated_questions(raw_content=body.raw_content, title=title)
    if not prepared.questions:
        detail = prepared.errors[0] if prepared.errors else "No valid question set found in assistant response"
        raise ValidationError(detail)

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

    created: list[PracticeProblem] = []
    for index, question in enumerate(prepared.questions):
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
        "discarded_count": prepared.discarded_count,
        "warnings": prepared.warnings,
    }


@router.post(
    "/extract",
    response_model=ExtractResponse,
    summary="Extract quiz questions",
    description="Generate quiz questions from course content nodes using LLM.",
)
async def extract_quiz(body: ExtractRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Extract questions from a content node or all nodes in a course."""
    await get_course_or_404(db, body.course_id, user_id=user.id)
    await ensure_llm_ready("Quiz generation")

    outcome = QuizExtractionOutcome()
    failures: list[Exception] = []
    results: list[QuizExtractionOutcome] = []
    try:
        if body.content_node_id:
            result = await db.execute(
                select(CourseContentTree).where(
                    CourseContentTree.id == body.content_node_id,
                    CourseContentTree.course_id == body.course_id,
                )
            )
            node = result.scalar_one_or_none()
            if not node or not node.content:
                raise NotFoundError("Content node not found or empty")

            outcome = await extract_questions(
                node.content,
                node.title,
                body.course_id,
                body.content_node_id,
                mode=body.mode,
                difficulty=body.difficulty,
            )
        else:
            import asyncio

            target_count = body.count or 10
            # Process a reasonable number of nodes -- ~2 questions per node
            max_nodes = min(max(target_count // 2, 3), 15)

            # Only generate quizzes from knowledge content, not syllabus/info
            result = await db.execute(
                select(CourseContentTree)
                .where(CourseContentTree.course_id == body.course_id)
                .where(CourseContentTree.content.isnot(None))
            )
            nodes = result.scalars().all()
            eligible = [
                n for n in nodes
                if n.content and len(n.content) > 100
                and n.content_category not in INFO_CATEGORIES
            ][:max_nodes]

            sem = asyncio.Semaphore(3)

            async def _extract(n):
                async with sem:
                    try:
                        return await asyncio.wait_for(
                            extract_questions(
                                n.content,
                                n.title,
                                body.course_id,
                                n.id,
                                mode=body.mode,
                                difficulty=body.difficulty,
                            ),
                            timeout=60,
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Quiz extraction timed out for node %s", n.title)
                        return QuizExtractionOutcome(
                            warnings=[f"{n.title}: extraction timed out."],
                            node_failures=[
                                QuizNodeFailure(
                                    node_id=str(n.id),
                                    title=n.title,
                                    reason="Quiz extraction timed out for this node.",
                                ),
                            ],
                        )

            results = await asyncio.gather(*[_extract(n) for n in eligible], return_exceptions=True)
            for item in results:
                if isinstance(item, QuizExtractionOutcome):
                    outcome.extend(item)
                elif isinstance(item, Exception):
                    failures.append(item)
            if failures and not outcome.problems and not outcome.node_failures:
                raise failures[0]
            if failures:
                logger.warning(
                    "Quiz extraction skipped %d/%d node(s) due to errors",
                    len(failures),
                    len(results),
                )
    except (ConnectionError, TimeoutError, ValueError, KeyError, RuntimeError) as exc:
        reraise_as_app_error(exc, "Quiz extraction failed")
    except SQLAlchemyError as exc:
        reraise_as_app_error(exc, "Quiz extraction failed")

    max_order_result = await db.execute(
        select(func.max(PracticeProblem.order_index)).where(
            PracticeProblem.course_id == body.course_id,
            PracticeProblem.is_diagnostic == False,
            PracticeProblem.is_archived == False,
        )
    )
    next_order = (max_order_result.scalar() or 0) + 1
    for index, problem in enumerate(outcome.problems, start=next_order):
        problem.order_index = index
        db.add(problem)
    await db.commit()

    warnings: list[str] = list(outcome.warnings)
    if failures:
        warnings.append(
            f"Skipped {len(failures)}/{len(results)} content node(s) due to extraction errors."
        )

    # Check prerequisite gaps for the generated problems' knowledge points
    try:
        kp_names: list[str] = []
        for p in outcome.problems:
            kp_list = p.knowledge_points if hasattr(p, "knowledge_points") else None
            if kp_list:
                kp_names.extend(kp_list if isinstance(kp_list, list) else [kp_list])
        if kp_names:
            from services.loom_graph import check_prerequisites_satisfied
            satisfied, gaps = await check_prerequisites_satisfied(
                db, user.id, body.course_id, list(set(kp_names)),
            )
            if not satisfied:
                gap_names = [g["concept"] for g in gaps[:3]]
                warnings.append(
                    f"Prerequisite gaps detected: {', '.join(gap_names)}. "
                    "Consider reviewing these concepts first."
                )
    except (ImportError, KeyError, AttributeError, LookupError) as e:
        logger.debug("Prerequisite check skipped: %s", type(e).__name__)

    return {
        "status": "ok",
        "problems_created": len(outcome.problems),
        "validated_count": outcome.validated_count,
        "repaired_count": outcome.repaired_count,
        "discarded_count": outcome.discarded_count,
        "node_failures": [failure.to_dict() for failure in outcome.node_failures],
        "warnings": warnings,
    }


# ── CAT Pre-test (Diagnostic Assessment) ──

import time

# In-memory session store (per-process). Keyed by (user_id, course_id).
# For production, swap with Redis or DB-backed session store.
_pretest_sessions: dict[tuple[str, str], dict] = {}
_SESSION_TTL_SECONDS = 30 * 60  # 30 minutes


def _session_key(user_id: uuid.UUID, course_id: uuid.UUID) -> tuple[str, str]:
    return (str(user_id), str(course_id))


def _cleanup_stale_sessions() -> None:
    """Remove sessions older than TTL to prevent memory leaks."""
    now = time.monotonic()
    stale = [k for k, v in _pretest_sessions.items() if now - v.get("created_at", 0) > _SESSION_TTL_SECONDS]
    for k in stale:
        del _pretest_sessions[k]


@router.post("/pretest/start", summary="Start diagnostic pre-test", description="Initialize a CAT session and return the first question concept.")
async def pretest_start(
    body: PretestStartRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a computerized adaptive pre-test for cold-start diagnosis."""
    if not settings.enable_experimental_cat:
        raise HTTPException(404, "CAT diagnostic pretest is experimental. Set ENABLE_EXPERIMENTAL_CAT=true to enable.")
    course = await get_course_or_404(db, body.course_id, user_id=user.id)

    from services.diagnosis.cat_pretest import (
        CATState,
        load_testable_concepts,
        select_next_item,
    )

    items = await load_testable_concepts(db, body.course_id)
    if len(items) < 3:
        raise ValidationError("Not enough concepts for diagnostic assessment (need at least 3)")

    state = CATState()
    first_item = select_next_item(state, items)
    if not first_item:
        raise ValidationError("No testable concepts available")

    # Fetch the associated practice problem for this concept (if any)
    question = await _get_concept_question(db, body.course_id, first_item.concept_id)

    # Store session (clean up stale ones first)
    _cleanup_stale_sessions()
    key = _session_key(user.id, body.course_id)
    _pretest_sessions[key] = {
        "state": state,
        "items": items,
        "created_at": time.monotonic(),
    }

    return {
        "status": "started",
        "total_concepts": len(items),
        "current_item": {
            "concept_id": str(first_item.concept_id),
            "concept_name": first_item.concept_name,
            "difficulty": first_item.difficulty,
            "bloom_level": first_item.bloom_level,
            "question": question,
        },
        "progress": {
            "answered": 0,
            "estimated_total": min(len(items), 20),
            "ability": state.theta,
        },
    }


@router.post("/pretest/answer", summary="Submit pre-test answer", description="Submit answer for current CAT item, get next question or finalization.")
async def pretest_answer(
    body: PretestAnswerRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Process a pre-test answer and return next item or final results."""
    if not settings.enable_experimental_cat:
        raise HTTPException(404, "CAT diagnostic pretest is experimental. Set ENABLE_EXPERIMENTAL_CAT=true to enable.")
    await get_course_or_404(db, body.course_id, user_id=user.id)

    from services.diagnosis.cat_pretest import (
        finalize_pretest,
        select_next_item,
        update_ability,
    )

    key = _session_key(user.id, body.course_id)
    session = _pretest_sessions.get(key)
    if not session:
        raise NotFoundError("No active pre-test session. Call /pretest/start first.")

    state = session["state"]
    items = session["items"]

    # Find the item that was answered
    current_item = None
    for item in items:
        if item.concept_id == body.concept_id:
            current_item = item
            break
    if not current_item:
        raise ValidationError("Invalid concept_id for this pre-test session")

    # Update ability estimate
    update_ability(state, current_item, body.correct)

    # Check if we should stop
    if state.should_stop:
        # Finalize and write mastery scores
        result = await finalize_pretest(db, user.id, body.course_id, state, items)
        del _pretest_sessions[key]
        return {
            "status": "completed",
            "result": result,
        }

    # Select next item
    next_item = select_next_item(state, items)
    if not next_item:
        # All items tested
        result = await finalize_pretest(db, user.id, body.course_id, state, items)
        del _pretest_sessions[key]
        return {
            "status": "completed",
            "result": result,
        }

    question = await _get_concept_question(db, body.course_id, next_item.concept_id)

    return {
        "status": "in_progress",
        "current_item": {
            "concept_id": str(next_item.concept_id),
            "concept_name": next_item.concept_name,
            "difficulty": next_item.difficulty,
            "bloom_level": next_item.bloom_level,
            "question": question,
        },
        "progress": {
            "answered": state.total_count,
            "correct": state.correct_count,
            "estimated_total": min(len(items), 20),
            "ability": round(state.theta, 3),
            "standard_error": round(state.standard_error, 3),
        },
    }


async def _get_concept_question(
    db: AsyncSession,
    course_id: uuid.UUID,
    concept_id: uuid.UUID,
) -> dict | None:
    """Try to find an existing practice problem for a concept, or return None."""
    result = await db.execute(
        select(PracticeProblem).where(
            PracticeProblem.course_id == course_id,
            PracticeProblem.is_archived == False,  # noqa: E712
        ).limit(50)
    )
    problems = result.scalars().all()

    # Match by knowledge_points linkage
    concept_str = str(concept_id)
    for p in problems:
        kp = getattr(p, "knowledge_points", None)
        if not kp:
            continue
        kp_list = kp if isinstance(kp, list) else [str(kp)]
        if concept_str in kp_list:
            return {
                "id": str(p.id),
                "question_type": p.question_type,
                "question": p.question,
                "options": p.options,
            }

    return None
