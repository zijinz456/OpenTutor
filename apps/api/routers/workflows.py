"""Compatibility workflow endpoints used by existing frontend clients.

These endpoints keep legacy `/api/workflows/*` paths functional while the
durable task-based architecture is used under the hood.
"""

from __future__ import annotations

import uuid
from collections import Counter

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.content import CourseContentTree
from models.ingestion import WrongAnswer
from models.practice import PracticeProblem
from models.study_plan import StudyPlan
from models.user import User
from services.auth.dependency import get_current_user
from schemas.study_plan import StudyPlanResponse
from services.course_access import get_course_or_404
from services.generated_assets import list_generated_asset_batches, save_generated_asset

router = APIRouter()


class ExamPrepRequest(BaseModel):
    course_id: uuid.UUID
    exam_topic: str | None = None
    days_until_exam: int = Field(default=7, ge=1, le=60)


class ExamPrepResponse(BaseModel):
    course: str
    topics_count: int
    readiness: dict[str, float]
    days_until_exam: int
    plan: str


class SaveStudyPlanRequest(BaseModel):
    course_id: uuid.UUID
    markdown: str
    title: str | None = None
    replace_batch_id: uuid.UUID | None = None


class WrongAnswerReviewResponse(BaseModel):
    review: str
    wrong_answer_count: int
    wrong_answer_ids: list[str]


def _build_exam_prep_markdown(
    *,
    course_name: str,
    days_until_exam: int,
    exam_topic: str | None,
    topics: list[str],
) -> str:
    heading = exam_topic.strip() if exam_topic else course_name
    lines = [
        f"# {days_until_exam}-Day Exam Prep Plan",
        "",
        f"Target: **{heading}**",
        "",
    ]
    if not topics:
        topics = ["Core concepts", "Common pitfalls", "Timed practice"]

    for day in range(1, days_until_exam + 1):
        idx = (day - 1) % len(topics)
        focus = topics[idx]
        secondary = topics[(idx + 1) % len(topics)] if len(topics) > 1 else None
        lines.append(f"## Day {day}")
        lines.append(f"- Primary focus: {focus}")
        if secondary and secondary != focus:
            lines.append(f"- Secondary focus: {secondary}")
        lines.append("- Practice: 30-45 minutes of mixed questions")
        lines.append("- Reflection: record 2 mistakes and 1 correction rule")
        lines.append("")

    lines.append("## Final 24 Hours")
    lines.append("- Run one timed mock set")
    lines.append("- Review your error log and formula/definition sheet")
    lines.append("- Keep answers concise and show reasoning steps")
    return "\n".join(lines).strip()


@router.post("/exam-prep", response_model=ExamPrepResponse)
async def exam_prep_plan(
    body: ExamPrepRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    course = await get_course_or_404(db, body.course_id, user_id=user.id)

    node_result = await db.execute(
        select(CourseContentTree.title)
        .where(CourseContentTree.course_id == body.course_id)
        .order_by(CourseContentTree.level.asc(), CourseContentTree.order_index.asc())
        .limit(120)
    )
    raw_titles = [title.strip() for title in node_result.scalars().all() if title and title.strip()]
    seen: set[str] = set()
    topics: list[str] = []
    for title in raw_titles:
        normalized = title.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        topics.append(title)
        if len(topics) >= 24:
            break

    days = int(body.days_until_exam)
    coverage = min(1.0, len(topics) / max(days * 2, 1))
    readiness = {
        "coverage": round(coverage, 2),
        "consistency": round(min(1.0, days / 14), 2),
        "confidence": round(max(0.2, min(0.9, 0.45 + coverage * 0.4)), 2),
    }
    plan = _build_exam_prep_markdown(
        course_name=course.name,
        days_until_exam=days,
        exam_topic=body.exam_topic,
        topics=topics,
    )
    return ExamPrepResponse(
        course=course.name,
        topics_count=len(topics),
        readiness=readiness,
        days_until_exam=days,
        plan=plan,
    )


@router.post("/study-plans/save")
async def save_study_plan(
    body: SaveStudyPlanRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, body.course_id, user_id=user.id)
    result = await save_generated_asset(
        db,
        user_id=user.id,
        course_id=body.course_id,
        asset_type="study_plan",
        title=body.title or "Study Plan",
        content={"markdown": body.markdown},
        metadata={"source": "workflow_compat"},
        replace_batch_id=body.replace_batch_id,
    )
    await db.commit()
    return result


@router.get("/study-plans/{course_id}")
async def list_study_plans(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, course_id, user_id=user.id)
    return await list_generated_asset_batches(
        db,
        user_id=user.id,
        course_id=course_id,
        asset_type="study_plan",
    )


@router.get("/courses/{course_id}/study-plans", response_model=list[StudyPlanResponse])
async def list_persisted_study_plans(
    course_id: uuid.UUID,
    limit: int = Query(default=5, ge=1, le=20),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return AI-generated StudyPlan records for the given course."""
    await get_course_or_404(db, course_id, user_id=user.id)
    result = await db.execute(
        select(StudyPlan)
        .where(StudyPlan.course_id == course_id, StudyPlan.user_id == user.id)
        .order_by(StudyPlan.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/wrong-answer-review", response_model=WrongAnswerReviewResponse)
async def wrong_answer_review(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_course_or_404(db, course_id, user_id=user.id)
    result = await db.execute(
        select(WrongAnswer, PracticeProblem)
        .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
        .where(
            WrongAnswer.user_id == user.id,
            WrongAnswer.course_id == course_id,
            WrongAnswer.mastered == False,  # noqa: E712
        )
        .order_by(WrongAnswer.created_at.desc())
        .limit(20)
    )
    rows = result.all()

    wrong_ids = [str(item.id) for item, _ in rows]
    if not rows:
        return WrongAnswerReviewResponse(
            review="# Wrong Answer Review\n\nNo unmastered items. Great work.",
            wrong_answer_count=0,
            wrong_answer_ids=[],
        )

    categories = Counter((item.error_category or "uncategorized") for item, _ in rows)
    lines = [
        "# Wrong Answer Review",
        "",
        f"- Unmastered items: **{len(rows)}**",
        "",
        "## Top Error Patterns",
    ]
    for category, count in categories.most_common():
        lines.append(f"- {category.replace('_', ' ')}: {count}")

    lines.append("")
    lines.append("## Priority Questions")
    for idx, (item, problem) in enumerate(rows[:8], start=1):
        lines.append(f"{idx}. **{problem.question}**")
        if item.user_answer:
            lines.append(f"   - Your answer: `{item.user_answer}`")
        if item.correct_answer:
            lines.append(f"   - Correct answer: `{item.correct_answer}`")
        if item.explanation:
            lines.append(f"   - Why: {item.explanation}")
        lines.append("")

    lines.append("## Next Action")
    lines.append("- Retry top 3 questions and explain your reasoning in one sentence each.")

    return WrongAnswerReviewResponse(
        review="\n".join(lines).strip(),
        wrong_answer_count=len(rows),
        wrong_answer_ids=wrong_ids,
    )
