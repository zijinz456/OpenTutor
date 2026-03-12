"""Progress analytics endpoints — trends, weekly reports, templates, forecasting."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.ingestion import StudySession
from models.progress import LearningProgress
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()


class ApplyTemplateRequest(BaseModel):
    template_id: uuid.UUID
    course_id: uuid.UUID | None = None


# ── Time-Series Analytics ──


@router.get("/courses/{course_id}/trends", summary="Get course learning trends", description="Return daily mastery, study time, and quiz accuracy trends for charts.")
async def get_learning_trends(
    course_id: uuid.UUID,
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get daily learning trends for charts: mastery, study time, quiz accuracy."""
    await get_course_or_404(db, course_id, user_id=user.id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    session_result = await db.execute(
        select(StudySession)
        .where(
            StudySession.user_id == user.id,
            StudySession.course_id == course_id,
            StudySession.started_at >= cutoff,
        )
        .order_by(StudySession.started_at)
    )
    sessions = session_result.scalars().all()

    progress_result = await db.execute(
        select(LearningProgress)
        .where(
            LearningProgress.user_id == user.id,
            LearningProgress.course_id == course_id,
        )
    )
    progress_rows = progress_result.scalars().all()

    from models.practice import PracticeResult
    quiz_result = await db.execute(
        select(PracticeResult)
        .where(
            PracticeResult.user_id == user.id,
            PracticeResult.answered_at >= cutoff,
        )
        .order_by(PracticeResult.answered_at)
    )
    quiz_rows = quiz_result.scalars().all()

    daily: dict[str, dict] = {}
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily[d] = {"date": d, "study_minutes": 0, "quiz_total": 0, "quiz_correct": 0}

    for s in sessions:
        if s.started_at:
            d = s.started_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["study_minutes"] += s.duration_minutes or 0

    for q in quiz_rows:
        if q.answered_at:
            d = q.answered_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["quiz_total"] += 1
                if q.is_correct:
                    daily[d]["quiz_correct"] += 1

    current_mastery = (
        sum(p.mastery_score for p in progress_rows) / len(progress_rows)
        if progress_rows else 0.0
    )

    trend_data = sorted(daily.values(), key=lambda x: x["date"])
    for entry in trend_data:
        entry["accuracy"] = (
            round(entry["quiz_correct"] / entry["quiz_total"] * 100, 1)
            if entry["quiz_total"] > 0 else None
        )

    return {
        "course_id": str(course_id),
        "days": days,
        "current_mastery": round(current_mastery * 100, 1),
        "trend": trend_data,
    }


@router.get("/trends", summary="Get global learning trends", description="Return daily learning trends aggregated across all courses.")
async def get_global_trends(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get global daily learning trends across all courses."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    session_result = await db.execute(
        select(StudySession)
        .where(StudySession.user_id == user.id, StudySession.started_at >= cutoff)
        .order_by(StudySession.started_at)
    )
    sessions = session_result.scalars().all()

    from models.practice import PracticeResult
    quiz_result = await db.execute(
        select(PracticeResult)
        .where(PracticeResult.user_id == user.id, PracticeResult.answered_at >= cutoff)
        .order_by(PracticeResult.answered_at)
    )
    quiz_rows = quiz_result.scalars().all()

    daily: dict[str, dict] = {}
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily[d] = {"date": d, "study_minutes": 0, "quiz_total": 0, "quiz_correct": 0}

    for s in sessions:
        if s.started_at:
            d = s.started_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["study_minutes"] += s.duration_minutes or 0

    for q in quiz_rows:
        if q.answered_at:
            d = q.answered_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["quiz_total"] += 1
                if q.is_correct:
                    daily[d]["quiz_correct"] += 1

    trend_data = sorted(daily.values(), key=lambda x: x["date"])
    for entry in trend_data:
        entry["accuracy"] = (
            round(entry["quiz_correct"] / entry["quiz_total"] * 100, 1)
            if entry["quiz_total"] > 0 else None
        )

    return {"days": days, "trend": trend_data}


# ── Weekly Report ──


@router.get("/weekly-report", summary="Get weekly report", description="Generate a weekly learning report comparing this week to last week.")
async def get_weekly_report(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a weekly learning report with this-week vs last-week comparison."""
    now = datetime.now(timezone.utc)
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = this_monday - timedelta(days=7)

    async def _week_stats(start: datetime, end: datetime) -> dict:
        sess_result = await db.execute(
            select(StudySession).where(
                StudySession.user_id == user.id,
                StudySession.started_at >= start,
                StudySession.started_at < end,
            )
        )
        sessions = sess_result.scalars().all()
        study_minutes = sum(s.duration_minutes or 0 for s in sessions)
        active_days = len({s.started_at.strftime("%Y-%m-%d") for s in sessions if s.started_at})

        from models.practice import PracticeResult
        quiz_result = await db.execute(
            select(PracticeResult).where(
                PracticeResult.user_id == user.id,
                PracticeResult.answered_at >= start,
                PracticeResult.answered_at < end,
            )
        )
        quizzes = quiz_result.scalars().all()
        quiz_total = len(quizzes)
        quiz_correct = sum(1 for q in quizzes if q.is_correct)
        accuracy = round(quiz_correct / quiz_total * 100, 1) if quiz_total > 0 else 0.0

        return {
            "study_minutes": study_minutes,
            "active_days": active_days,
            "quiz_total": quiz_total,
            "quiz_correct": quiz_correct,
            "accuracy": accuracy,
        }

    this_week = await _week_stats(this_monday, now)
    last_week = await _week_stats(last_monday, this_monday)

    progress_result = await db.execute(
        select(LearningProgress).where(LearningProgress.user_id == user.id)
    )
    progress_rows = progress_result.scalars().all()
    mastery_avg = round(
        sum(p.mastery_score for p in progress_rows) / len(progress_rows) * 100, 1
    ) if progress_rows else 0.0

    deltas = {
        "study_minutes": this_week["study_minutes"] - last_week["study_minutes"],
        "accuracy": round(this_week["accuracy"] - last_week["accuracy"], 1),
        "quiz_total": this_week["quiz_total"] - last_week["quiz_total"],
    }

    highlights: list[str] = []
    if this_week["active_days"] >= 5:
        highlights.append(f"Studied {this_week['active_days']} days this week!")
    if deltas["accuracy"] > 0:
        highlights.append(f"Quiz accuracy improved by {deltas['accuracy']}%")
    if this_week["quiz_total"] > 0:
        highlights.append(f"Completed {this_week['quiz_total']} quiz questions")
    if this_week["study_minutes"] > 0:
        highlights.append(f"Studied for {this_week['study_minutes']} minutes total")
    if not highlights:
        highlights.append("Start studying to see your weekly progress!")

    return {
        "period": {
            "start": this_monday.strftime("%Y-%m-%d"),
            "end": now.strftime("%Y-%m-%d"),
        },
        "this_week": this_week,
        "last_week": last_week,
        "deltas": deltas,
        "mastery_avg": mastery_avg,
        "highlights": highlights[:4],
    }


# ── Memory Stats ──


@router.get("/memory-stats", summary="Get memory statistics", description="Return memory consolidation statistics for the current user.")
async def get_memory_stats_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get memory consolidation statistics."""
    from services.agent.memory_agent import get_memory_stats

    return await get_memory_stats(db, user.id)


@router.post("/memory-consolidate", summary="Trigger memory consolidation", description="Run memory consolidation pipeline for the current user.")
async def trigger_consolidation(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Trigger memory consolidation for the user."""
    from services.memory.pipeline import consolidate_memory

    result = await consolidate_memory(db, user.id)
    await db.commit()
    return result


# ── Templates ──


@router.get("/templates", summary="List learning templates", description="Return all available learning templates.")
async def list_templates(db: AsyncSession = Depends(get_db)):
    """List all available learning templates."""
    from services.templates.system import list_templates

    return await list_templates(db)


@router.post("/templates/apply", summary="Apply a learning template", description="Apply a learning template to the user's preferences.")
async def apply_template(
    body: ApplyTemplateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a learning template to the user's preferences."""
    from services.templates.system import apply_template

    result = await apply_template(db, user.id, body.template_id, body.course_id)
    await db.commit()
    return result


@router.post("/templates/seed", summary="Seed built-in templates", description="Seed built-in learning templates into the database.")
async def seed_templates(db: AsyncSession = Depends(get_db)):
    """Seed built-in learning templates (run once on setup)."""
    from services.templates.system import seed_builtin_templates

    count = await seed_builtin_templates(db)
    await db.commit()
    return {"seeded": count}
