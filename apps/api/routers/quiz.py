"""Quiz endpoints: extract questions, list problems, submit answers, and save generated sets."""

import logging
import uuid

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session, get_db
from models.content import CourseContentTree
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.parser.quiz import extract_questions
from services.practice.annotation import build_practice_problem, parse_question_array

router = APIRouter()


class ExtractRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None


class SubmitAnswerRequest(BaseModel):
    problem_id: uuid.UUID
    user_answer: str


class SaveGeneratedRequest(BaseModel):
    course_id: uuid.UUID
    raw_content: str
    title: str | None = None
    replace_batch_id: uuid.UUID | None = None


class ProblemResponse(BaseModel):
    id: uuid.UUID
    question_type: str
    question: str
    options: dict | None
    order_index: int

    model_config = {"from_attributes": True}


class AnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str | None
    explanation: str | None


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
        raise HTTPException(status_code=400, detail="No valid question set found in assistant response")

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
            raise HTTPException(status_code=404, detail="Generated batch not found")
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
    # Verify course ownership
    await get_course_or_404(db, body.course_id, user_id=user.id)

    if body.content_node_id:
        result = await db.execute(
            select(CourseContentTree).where(CourseContentTree.id == body.content_node_id)
        )
        node = result.scalar_one_or_none()
        if not node or not node.content:
            raise HTTPException(status_code=404, detail="Content node not found or empty")

        problems = await extract_questions(
            node.content, node.title, body.course_id, body.content_node_id
        )
    else:
        # Extract from all content nodes in the course
        result = await db.execute(
            select(CourseContentTree)
            .where(CourseContentTree.course_id == body.course_id)
            .where(CourseContentTree.content.isnot(None))
        )
        nodes = result.scalars().all()
        problems = []
        for node in nodes[:50]:  # Limit to 50 nodes to prevent excessive LLM calls
            if node.content and len(node.content) > 100:
                node_problems = await extract_questions(
                    node.content, node.title, body.course_id, node.id
                )
                problems.extend(node_problems)

    for p in problems:
        db.add(p)
    await db.commit()

    return {"status": "ok", "problems_created": len(problems)}


@router.get("/{course_id}", response_model=list[ProblemResponse])
async def list_problems(course_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List user-facing practice problems for a course.

    Diagnostic pair questions are excluded from the default quiz list because
    they are remediation artifacts, not part of the main practice set.
    """
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
            # Only auto-derive for non-diagnostic problems with difficulty_layer >= 2
            if problem.is_diagnostic or (problem.difficulty_layer and problem.difficulty_layer < 2):
                return
            # Use the derive logic inline (lighter than calling the endpoint)
            from services.llm.router import get_llm_client
            from services.practice.annotation import build_practice_problem
            import json

            client = get_llm_client()
            metadata_str = ""
            if problem.problem_metadata:
                meta = problem.problem_metadata
                parts = []
                if meta.get("core_concept"):
                    parts.append(f"Core concept: {meta['core_concept']}")
                if meta.get("potential_traps"):
                    parts.append(f"Known traps to remove: {', '.join(meta['potential_traps'])}")
                if parts:
                    metadata_str = "\nQuestion metadata:\n" + "\n".join(parts)

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
{{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}} or null, "correct_answer": "...", "explanation": "...", "simplifications_made": ["list of simplifications"], "core_concept_preserved": "concept name"}}"""

            response, _ = await client.chat(
                "You design diagnostic questions. Output valid JSON only.", prompt,
            )
            try:
                derived = json.loads(response)
            except json.JSONDecodeError:
                derived = {"question": response[:500]}

            if not derived.get("question"):
                return

            new_problem = build_practice_problem(
                course_id=problem.course_id,
                content_node_id=problem.content_node_id,
                title=(problem.problem_metadata or {}).get("core_concept", problem.question[:80]),
                question={
                    "question_type": problem.question_type,
                    "question": derived.get("question", ""),
                    "options": derived.get("options"),
                    "correct_answer": derived.get("correct_answer") or wa.correct_answer,
                    "explanation": derived.get("explanation", "Simplified diagnostic check."),
                    "difficulty_layer": 1,
                    "problem_metadata": {
                        "core_concept": derived.get("core_concept_preserved", ""),
                        "bloom_level": "understand",
                        "potential_traps": [],
                        "layer_justification": "Auto-generated diagnostic pair.",
                    },
                },
                order_index=problem.order_index,
                knowledge_points=wa.knowledge_points or problem.knowledge_points,
                source="derived",
                parent_problem_id=problem.id,
                is_diagnostic=True,
                difficulty_layer_default=1,
                extra_metadata={
                    "simplifications_made": derived.get("simplifications_made", []),
                    "core_concept_preserved": derived.get("core_concept_preserved", ""),
                    "original_problem_id": str(problem.id),
                    "wrong_answer_id": str(wa.id),
                    "auto_generated": True,
                },
            )
            db.add(new_problem)
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
        raise HTTPException(status_code=404, detail="Problem not found")

    # Check correctness
    is_correct = False
    if problem.correct_answer:
        is_correct = body.user_answer.strip().lower() == problem.correct_answer.strip().lower()

    # Record result with layer metadata
    pr = PracticeResult(
        problem_id=problem.id,
        user_id=user.id,
        user_answer=body.user_answer,
        is_correct=is_correct,
        ai_explanation=problem.explanation,
        difficulty_layer=problem.difficulty_layer,
    )

    # v4: Structured error classification for wrong answers
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

    # v3: Auto-archive wrong answers for review system
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

    # v4: Update progress with weighted decay mastery + FSRS
    try:
        from services.progress.tracker import update_quiz_result
        await update_quiz_result(
            db, user.id, problem.course_id, problem.content_node_id,
            is_correct=is_correct,
            error_category=error_category,
        )
    except Exception as e:
        logger.warning("Progress update failed (best-effort): %s", e)

    await db.commit()

    # Auto-derive diagnostic pair in background for wrong answers
    if not is_correct and wa:
        background_tasks.add_task(_auto_derive_diagnostic, wa.id, user.id)

    return AnswerResponse(
        is_correct=is_correct,
        correct_answer=problem.correct_answer,
        explanation=problem.explanation,
    )
