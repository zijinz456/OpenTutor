"""Wrong answer management API — v3 error review system.

Endpoints for listing wrong answers, retrying, and generating derived questions.
"""

import json
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.ingestion import WrongAnswer
from models.practice import PracticeProblem
from models.user import User
from services.auth.dependency import get_current_user

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
        raise HTTPException(status_code=404, detail="Wrong answer not found")

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
    """Generate a similar question based on the wrong answer's knowledge points.

    Uses the ExerciseAgent to create a derived practice problem.
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
        raise HTTPException(status_code=404, detail="Wrong answer not found")

    wa, problem = row

    # Use LLM to generate a similar question
    from services.llm.router import get_llm_client

    client = get_llm_client()
    prompt = f"""Based on this question that the student got wrong, generate ONE similar practice question.

Original question: {problem.question}
Question type: {problem.question_type}
Student's wrong answer: {wa.user_answer}
Correct answer: {wa.correct_answer}
Error category: {wa.error_category or 'unknown'}

Generate a question that tests the same concept but with different numbers/context.
Return JSON: {{"question": "...", "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}} or null, "correct_answer": "...", "explanation": "..."}}"""

    response, _ = await client.chat(
        "You generate educational practice questions and output valid JSON only.",
        prompt,
    )

    try:
        derived = json.loads(response)
    except json.JSONDecodeError:
        # Try to extract the outermost JSON object from a mixed response.
        json_match = re.search(r"\{[\s\S]*\}", response)
        if json_match:
            try:
                derived = json.loads(json_match.group())
            except json.JSONDecodeError:
                derived = {
                    "question": response,
                    "options": None,
                    "correct_answer": None,
                    "explanation": None,
                }
        else:
            derived = {"question": response, "options": None, "correct_answer": None, "explanation": None}

    # Save as a new practice problem
    new_problem = PracticeProblem(
        course_id=problem.course_id,
        content_node_id=problem.content_node_id,
        question_type=problem.question_type,
        question=derived.get("question", ""),
        options=derived.get("options"),
        correct_answer=derived.get("correct_answer"),
        explanation=derived.get("explanation"),
        knowledge_points=wa.knowledge_points or problem.knowledge_points,
        source="derived",
    )
    db.add(new_problem)
    await db.commit()
    await db.refresh(new_problem)

    return {
        "problem_id": str(new_problem.id),
        "question": new_problem.question,
        "question_type": new_problem.question_type,
        "options": new_problem.options,
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

    return {
        "total": total,
        "mastered": mastered,
        "unmastered": total - mastered,
        "by_category": by_category,
    }
