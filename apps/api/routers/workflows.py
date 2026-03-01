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
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.activity.tasks import create_task

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


class SaveStudyPlanRequest(BaseModel):
    course_id: uuid.UUID
    markdown: str
    title: str | None = None
    replace_batch_id: uuid.UUID | None = None


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
async def semester_init(body: SemesterInitRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """WF-1: Initialize a new semester with courses and study plan."""
    from services.workflow.semester_init import run_semester_init

    try:
        result = await run_semester_init(db, user.id, body.semester_name, body.courses)
        await create_task(
            db,
            user_id=user.id,
            task_type="semester_init",
            title=f"Initialized {body.semester_name}",
            summary=f"Created {len(result.get('courses', []))} courses and generated a semester plan.",
            source="workflow",
            result_json=result,
        )
        await db.commit()
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("WF-1 failed: user_id=%s semester=%s", user.id, body.semester_name)
        raise HTTPException(status_code=500, detail="Semester init failed") from e


@router.get("/weekly-prep")
async def weekly_prep(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """WF-2: Generate weekly study plan based on deadlines and progress."""
    from services.workflow.weekly_prep import run_weekly_prep

    try:
        result = await run_weekly_prep(db, user.id)
        await create_task(
            db,
            user_id=user.id,
            task_type="weekly_prep",
            title="Generated weekly prep plan",
            summary=(result.get("plan", "") or "Weekly plan generated.")[:300],
            source="workflow",
            result_json=result,
        )
        await db.commit()
        return result
    except Exception as e:
        logger.exception("WF-2 failed: user_id=%s", user.id)
        raise HTTPException(status_code=500, detail="Weekly prep failed") from e


@router.post("/assignment-analysis")
async def assignment_analysis(body: AssignmentAnalysisRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """WF-3: Analyze an assignment and generate approach guide."""
    from services.workflow.assignment_analysis import run_assignment_analysis

    try:
        result = await run_assignment_analysis(db, user.id, body.assignment_id)
        _raise_if_service_error(result)
        await create_task(
            db,
            user_id=user.id,
            course_id=uuid.UUID(result["course_id"]) if result.get("course_id") else None,
            task_type="assignment_analysis",
            title=f"Analyzed assignment: {result.get('title', 'Assignment')}",
            summary=(result.get("analysis", "") or "Assignment analysis generated.")[:300],
            source="workflow",
            metadata_json={"assignment_id": result.get("assignment_id")},
            result_json=result,
        )
        await db.commit()
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """WF-5: Generate review material based on wrong answers."""
    from services.workflow.wrong_answer_review import run_wrong_answer_review

    try:
        result = await run_wrong_answer_review(db, user.id, course_id)
        await create_task(
            db,
            user_id=user.id,
            course_id=course_id,
            task_type="wrong_answer_review",
            title="Generated wrong-answer review",
            summary=(result.get("review", "") or "Wrong-answer review generated.")[:300],
            source="workflow",
            metadata_json={"wrong_answer_count": result.get("wrong_answer_count", 0)},
            result_json=result,
        )
        await db.commit()
        return result
    except Exception as e:
        logger.exception("WF-5 failed: user_id=%s course_id=%s", user.id, course_id)
        raise HTTPException(status_code=500, detail="Wrong-answer review failed") from e


@router.post("/wrong-answer-review/mark")
async def mark_wrong_answers_reviewed(
    body: MarkReviewedRequest,
    user: User = Depends(get_current_user),
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
async def exam_prep(body: ExamPrepRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """WF-6: Generate exam preparation plan."""
    from services.workflow.exam_prep import run_exam_prep

    try:
        result = await run_exam_prep(
            db, user.id, body.course_id, body.exam_topic, body.days_until_exam
        )
        await create_task(
            db,
            user_id=user.id,
            course_id=body.course_id,
            task_type="exam_prep",
            title="Generated exam prep plan",
            summary=(result.get("plan", "") or "Exam prep plan generated.")[:300],
            source="workflow",
            metadata_json={"days_until_exam": body.days_until_exam, "exam_topic": body.exam_topic},
            result_json=result,
        )
        await db.commit()
        return result
    except Exception as e:
        logger.exception(
            "WF-6 failed: user_id=%s course_id=%s days_until_exam=%d",
            user.id,
            body.course_id,
            body.days_until_exam,
        )
        raise HTTPException(status_code=500, detail="Exam prep failed") from e


@router.post("/study-plans/save")
async def save_study_plan(
    body: SaveStudyPlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.generated_assets import save_generated_asset

    course = await get_course_or_404(db, body.course_id, user_id=user.id)

    try:
        result = await save_generated_asset(
            db,
            user_id=user.id,
            course_id=body.course_id,
            asset_type="study_plan",
            title=body.title or course.name,
            content={"markdown": body.markdown},
            metadata=None,
            replace_batch_id=body.replace_batch_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await db.commit()
    return result


@router.get("/study-plans/{course_id}")
async def list_study_plans(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from services.generated_assets import list_generated_asset_batches

    await get_course_or_404(db, course_id, user_id=user.id)

    return await list_generated_asset_batches(
        db,
        user_id=user.id,
        course_id=course_id,
        asset_type="study_plan",
    )
