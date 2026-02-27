"""Quiz endpoints: extract questions, list problems, submit answers."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.content import CourseContentTree
from models.practice import PracticeProblem, PracticeResult
from models.user import User
from services.auth.dependency import get_current_user
from services.parser.quiz import extract_questions

router = APIRouter()


class ExtractRequest(BaseModel):
    course_id: uuid.UUID
    content_node_id: uuid.UUID | None = None


class SubmitAnswerRequest(BaseModel):
    problem_id: uuid.UUID
    user_answer: str


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


@router.post("/extract")
async def extract_quiz(body: ExtractRequest, db: AsyncSession = Depends(get_db)):
    """Extract questions from a content node or all nodes in a course."""
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
        for node in nodes:
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
async def list_problems(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """List all practice problems for a course."""
    result = await db.execute(
        select(PracticeProblem)
        .where(PracticeProblem.course_id == course_id)
        .order_by(PracticeProblem.order_index)
    )
    return result.scalars().all()


@router.post("/submit", response_model=AnswerResponse)
async def submit_answer(body: SubmitAnswerRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
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

    # Record result
    pr = PracticeResult(
        problem_id=problem.id,
        user_id=user.id,
        user_answer=body.user_answer,
        is_correct=is_correct,
        ai_explanation=problem.explanation,
    )
    db.add(pr)

    # v3: Auto-archive wrong answers for review system
    if not is_correct:
        from models.ingestion import WrongAnswer
        wa = WrongAnswer(
            user_id=user.id,
            problem_id=problem.id,
            course_id=problem.course_id,
            user_answer=body.user_answer,
            correct_answer=problem.correct_answer,
            explanation=problem.explanation,
            knowledge_points=problem.knowledge_points,
        )
        db.add(wa)

    await db.commit()

    return AnswerResponse(
        is_correct=is_correct,
        correct_answer=problem.correct_answer,
        explanation=problem.explanation,
    )
