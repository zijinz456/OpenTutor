"""Workflow API endpoints.

Exposes the 6 workflow pipelines:
- WF-1: Semester initialization
- WF-2: Weekly prep
- WF-3: Assignment analysis
- WF-4: Study session (exposed via /chat)
- WF-5: Wrong answer review
- WF-6: Exam preparation
"""

import uuid
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from routers.courses import get_or_create_user

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Request schemas ──


class SemesterInitRequest(BaseModel):
    semester_name: str
    courses: list[dict]  # [{"name": "CS101", "type": "stem", "description": "..."}]


class AssignmentAnalysisRequest(BaseModel):
    assignment_id: uuid.UUID


class ExamPrepRequest(BaseModel):
    course_id: uuid.UUID
    exam_topic: str | None = None
    days_until_exam: int = 7


class MarkReviewedRequest(BaseModel):
    wrong_answer_ids: list[uuid.UUID]


def _raise_if_service_error(result: dict) -> None:
    """Normalize service-level error dict into HTTP exceptions."""
    error = result.get("error")
    if not error:
        return
    if error == "Assignment not found":
        raise HTTPException(status_code=404, detail=error)
    raise HTTPException(status_code=400, detail=error)


# ── Endpoints ──


@router.post("/semester-init")
async def semester_init(body: SemesterInitRequest, db: AsyncSession = Depends(get_db)):
    """WF-1: Initialize a new semester with courses and study plan."""
    from services.workflow.semester_init import run_semester_init

    user = await get_or_create_user(db)
    try:
        result = await run_semester_init(db, user.id, body.semester_name, body.courses)
        await db.commit()
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("WF-1 failed: user_id=%s semester=%s", user.id, body.semester_name)
        raise HTTPException(status_code=500, detail="Semester init failed") from e


@router.get("/weekly-prep")
async def weekly_prep(db: AsyncSession = Depends(get_db)):
    """WF-2: Generate weekly study plan based on deadlines and progress."""
    from services.workflow.weekly_prep import run_weekly_prep

    user = await get_or_create_user(db)
    try:
        return await run_weekly_prep(db, user.id)
    except Exception as e:
        logger.exception("WF-2 failed: user_id=%s", user.id)
        raise HTTPException(status_code=500, detail="Weekly prep failed") from e


@router.post("/assignment-analysis")
async def assignment_analysis(body: AssignmentAnalysisRequest, db: AsyncSession = Depends(get_db)):
    """WF-3: Analyze an assignment and generate approach guide."""
    from services.workflow.assignment_analysis import run_assignment_analysis

    user = await get_or_create_user(db)
    try:
        result = await run_assignment_analysis(db, user.id, body.assignment_id)
        _raise_if_service_error(result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(
            "WF-3 failed: user_id=%s assignment_id=%s",
            user.id,
            body.assignment_id,
        )
        raise HTTPException(status_code=500, detail="Assignment analysis failed") from e


@router.get("/wrong-answer-review")
async def wrong_answer_review(
    course_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """WF-5: Generate review material based on wrong answers."""
    from services.workflow.wrong_answer_review import run_wrong_answer_review

    user = await get_or_create_user(db)
    try:
        return await run_wrong_answer_review(db, user.id, course_id)
    except Exception as e:
        logger.exception("WF-5 failed: user_id=%s course_id=%s", user.id, course_id)
        raise HTTPException(status_code=500, detail="Wrong-answer review failed") from e


@router.post("/wrong-answer-review/mark")
async def mark_wrong_answers_reviewed(
    body: MarkReviewedRequest,
    db: AsyncSession = Depends(get_db),
):
    """Mark wrong answers as reviewed (increments review count)."""
    from services.workflow.wrong_answer_review import mark_as_reviewed

    try:
        count = await mark_as_reviewed(db, body.wrong_answer_ids)
        await db.commit()
        return {"marked": count}
    except Exception as e:
        logger.exception(
            "WF-5 mark reviewed failed: wrong_answer_count=%d",
            len(body.wrong_answer_ids),
        )
        raise HTTPException(status_code=500, detail="Mark reviewed failed") from e


@router.post("/exam-prep")
async def exam_prep(body: ExamPrepRequest, db: AsyncSession = Depends(get_db)):
    """WF-6: Generate exam preparation plan."""
    from services.workflow.exam_prep import run_exam_prep

    user = await get_or_create_user(db)
    try:
        return await run_exam_prep(
            db, user.id, body.course_id, body.exam_topic, body.days_until_exam
        )
    except Exception as e:
        logger.exception(
            "WF-6 failed: user_id=%s course_id=%s days_until_exam=%d",
            user.id,
            body.course_id,
            body.days_until_exam,
        )
        raise HTTPException(status_code=500, detail="Exam prep failed") from e
