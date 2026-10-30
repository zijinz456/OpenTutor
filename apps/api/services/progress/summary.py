"""One place for the progress aggregates the routers and agents read.

Everything here is derived from the ledger tables only:

- ``learning_progress`` — mastery, status, gap type and accumulated study time
  (``time_spent_minutes``, written by ``tracker.update_quiz_result`` from
  answer time).  There is no separate study-session table any more.
- ``practice_results`` — per-attempt facts (``answered_at``,
  ``answer_time_ms``, ``is_correct``) for anything that needs a time window.
- ``wrong_answers`` — error bookkeeping.

Routers (``/progress/courses/{id}``, ``/progress/overview``,
``/progress/weekly-report``, ``/wrong-answers/{id}/stats``) and the agent
tools call these instead of recomputing the same sums.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.content import CourseContentTree
from models.course import Course
from models.ingestion import WrongAnswer
from models.practice import PracticeProblem, PracticeResult
from models.progress import LearningProgress

# Mirror of tracker.update_quiz_result: a single answer never counts for more
# than 30 minutes of study time (idle tab guard).
_MAX_MINUTES_PER_ANSWER = 30


def _answer_minutes(answer_time_ms: int | None) -> int:
    if not answer_time_ms or answer_time_ms <= 0:
        return 0
    return min(int(round(answer_time_ms / 60000)), _MAX_MINUTES_PER_ANSWER)


# ── Study time ──


async def study_minutes_total(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID | None = None,
) -> int:
    """Lifetime study minutes from the ledger (sum of learning_progress.time_spent_minutes)."""
    query = select(func.coalesce(func.sum(LearningProgress.time_spent_minutes), 0)).where(
        LearningProgress.user_id == user_id,
    )
    if course_id is not None:
        query = query.where(LearningProgress.course_id == course_id)
    return int((await db.execute(query)).scalar() or 0)


async def practice_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    start: datetime,
    end: datetime | None = None,
    course_id: uuid.UUID | None = None,
) -> list[tuple[datetime, int, bool]]:
    """Attempt facts in a window: (answered_at, study_minutes, is_correct)."""
    query = (
        select(PracticeResult.answered_at, PracticeResult.answer_time_ms, PracticeResult.is_correct)
        .join(PracticeProblem, PracticeProblem.id == PracticeResult.problem_id)
        .where(PracticeResult.user_id == user_id, PracticeResult.answered_at >= start)
        .order_by(PracticeResult.answered_at)
    )
    if end is not None:
        query = query.where(PracticeResult.answered_at < end)
    if course_id is not None:
        query = query.where(PracticeProblem.course_id == course_id)
    rows = (await db.execute(query)).all()
    return [(answered_at, _answer_minutes(ms), bool(correct)) for answered_at, ms, correct in rows]


async def daily_activity(
    db: AsyncSession,
    user_id: uuid.UUID,
    days: int,
    course_id: uuid.UUID | None = None,
) -> list[dict]:
    """Per-day study minutes and quiz counts for the last ``days`` days."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    daily: dict[str, dict] = {}
    for i in range(days):
        d = (now - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily[d] = {"date": d, "study_minutes": 0, "quiz_total": 0, "quiz_correct": 0}

    for answered_at, minutes, correct in await practice_activity(db, user_id, cutoff, course_id=course_id):
        if not answered_at:
            continue
        d = answered_at.strftime("%Y-%m-%d")
        if d not in daily:
            continue
        daily[d]["study_minutes"] += minutes
        daily[d]["quiz_total"] += 1
        if correct:
            daily[d]["quiz_correct"] += 1

    trend = sorted(daily.values(), key=lambda x: x["date"])
    for entry in trend:
        entry["accuracy"] = (
            round(entry["quiz_correct"] / entry["quiz_total"] * 100, 1)
            if entry["quiz_total"] > 0 else None
        )
    return trend


async def window_stats(
    db: AsyncSession, user_id: uuid.UUID, start: datetime, end: datetime,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Study minutes, active days and quiz accuracy between ``start`` and ``end``."""
    rows = await practice_activity(db, user_id, start, end, course_id=course_id)
    study_minutes = sum(m for _, m, _ in rows)
    active_days = len({ts.strftime("%Y-%m-%d") for ts, _, _ in rows if ts})
    quiz_total = len(rows)
    quiz_correct = sum(1 for _, _, c in rows if c)
    return {
        "study_minutes": study_minutes,
        "active_days": active_days,
        "quiz_total": quiz_total,
        "quiz_correct": quiz_correct,
        "accuracy": round(quiz_correct / quiz_total * 100, 1) if quiz_total > 0 else 0.0,
    }


async def last_activity_at(
    db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID | None = None,
) -> datetime | None:
    """Most recent ledger activity (last graded attempt or study time entry)."""
    lp = select(func.max(LearningProgress.last_studied_at)).where(LearningProgress.user_id == user_id)
    pr = (
        select(func.max(PracticeResult.answered_at))
        .join(PracticeProblem, PracticeProblem.id == PracticeResult.problem_id)
        .where(PracticeResult.user_id == user_id)
    )
    if course_id is not None:
        lp = lp.where(LearningProgress.course_id == course_id)
        pr = pr.where(PracticeProblem.course_id == course_id)
    candidates = [(await db.execute(lp)).scalar(), (await db.execute(pr)).scalar()]
    stamps = []
    for ts in candidates:
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        stamps.append(ts)
    return max(stamps) if stamps else None


# ── Wrong answers ──


async def wrong_answer_stats(db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID) -> dict:
    """Totals and breakdowns for a course's wrong answers."""
    rows = (await db.execute(
        select(WrongAnswer.error_category, WrongAnswer.diagnosis, WrongAnswer.mastered).where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user_id,
        )
    )).all()
    total = len(rows)
    mastered = sum(1 for _, _, m in rows if m)
    by_category: dict[str, int] = {}
    by_diagnosis: dict[str, int] = {}
    for category, diagnosis, _ in rows:
        key = category or "uncategorized"
        by_category[key] = by_category.get(key, 0) + 1
        if diagnosis:
            by_diagnosis[diagnosis] = by_diagnosis.get(diagnosis, 0) + 1
    return {
        "total": total,
        "mastered": mastered,
        "unmastered": total - mastered,
        "by_category": by_category,
        "by_diagnosis": by_diagnosis,
    }


# ── Course / user summaries ──


def _gap_breakdown(entries) -> dict[str, int]:
    breakdown: dict[str, int] = {}
    for entry in entries:
        if entry.gap_type:
            breakdown[entry.gap_type] = breakdown.get(entry.gap_type, 0) + 1
    return breakdown


async def course_summary(db: AsyncSession, user_id: uuid.UUID, course_id: uuid.UUID) -> dict:
    """Progress overview for one course (what ``/progress/courses/{id}`` returns)."""
    total_nodes = (await db.execute(
        select(func.count(CourseContentTree.id)).where(CourseContentTree.course_id == course_id)
    )).scalar() or 0

    entries = (await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
        )
    )).scalars().all()

    mastered = sum(1 for p in entries if p.status == "mastered")
    reviewed = sum(1 for p in entries if p.status == "reviewed")
    in_progress = sum(1 for p in entries if p.status == "in_progress")
    total_time = sum(p.time_spent_minutes or 0 for p in entries)
    avg_mastery = sum(p.mastery_score for p in entries) / len(entries) if entries else 0.0

    return {
        "course_id": str(course_id),
        "total_nodes": total_nodes,
        "mastered": mastered,
        "reviewed": reviewed,
        "in_progress": in_progress,
        "not_started": max(0, total_nodes - mastered - reviewed - in_progress),
        "total_study_minutes": total_time,
        "average_mastery": avg_mastery,
        "completion_percent": (mastered + reviewed) / max(total_nodes, 1) * 100,
        "gap_type_breakdown": _gap_breakdown(entries),
        "wrong_answers": await wrong_answer_stats(db, user_id, course_id),
    }


async def overview(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """Cross-course overview (what ``/progress/overview`` returns)."""
    courses = (await db.execute(
        select(Course).where(Course.user_id == user_id).order_by(Course.created_at.desc())
    )).scalars().all()
    course_ids = [course.id for course in courses]
    if not course_ids:
        return {
            "total_courses": 0,
            "total_study_minutes": 0,
            "average_mastery": 0.0,
            "gap_type_breakdown": {},
            "diagnosis_breakdown": {},
            "error_category_breakdown": {},
            "course_summaries": [],
        }

    progress_rows = (await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id.in_(course_ids),
        )
    )).scalars().all()
    wrong_rows = (await db.execute(
        select(WrongAnswer).where(
            WrongAnswer.user_id == user_id,
            WrongAnswer.course_id.in_(course_ids),
        )
    )).scalars().all()

    progress_by_course: dict[uuid.UUID, list[LearningProgress]] = {cid: [] for cid in course_ids}
    wrong_by_course: dict[uuid.UUID, list[WrongAnswer]] = {cid: [] for cid in course_ids}
    diagnosis_breakdown: dict[str, int] = {}
    error_category_breakdown: dict[str, int] = {}

    for progress in progress_rows:
        progress_by_course.setdefault(progress.course_id, []).append(progress)
    for wa in wrong_rows:
        wrong_by_course.setdefault(wa.course_id, []).append(wa)
        if wa.diagnosis:
            diagnosis_breakdown[wa.diagnosis] = diagnosis_breakdown.get(wa.diagnosis, 0) + 1
        if wa.error_category:
            error_category_breakdown[wa.error_category] = error_category_breakdown.get(wa.error_category, 0) + 1

    course_summaries = []
    for course in courses:
        course_progress = progress_by_course.get(course.id, [])
        course_wrong = wrong_by_course.get(course.id, [])
        course_summaries.append({
            "course_id": str(course.id),
            "course_name": course.name,
            "average_mastery": (
                sum(item.mastery_score for item in course_progress) / len(course_progress)
                if course_progress else 0.0
            ),
            "study_minutes": sum(item.time_spent_minutes or 0 for item in course_progress),
            "wrong_answers": len(course_wrong),
            "diagnosed_count": sum(1 for item in course_wrong if item.diagnosis),
            "gap_types": _gap_breakdown(course_progress),
        })

    all_scores = [row.mastery_score for row in progress_rows]
    return {
        "total_courses": len(courses),
        "total_study_minutes": sum(row.time_spent_minutes or 0 for row in progress_rows),
        "average_mastery": sum(all_scores) / len(all_scores) if all_scores else 0.0,
        "gap_type_breakdown": _gap_breakdown(progress_rows),
        "diagnosis_breakdown": diagnosis_breakdown,
        "error_category_breakdown": error_category_breakdown,
        "course_summaries": course_summaries,
    }


async def weekly_report(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """This-week vs last-week comparison (what ``/progress/weekly-report`` returns)."""
    now = datetime.now(timezone.utc)
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = this_monday - timedelta(days=7)

    this_week = await window_stats(db, user_id, this_monday, now)
    last_week = await window_stats(db, user_id, last_monday, this_monday)

    progress_rows = (await db.execute(
        select(LearningProgress.mastery_score).where(LearningProgress.user_id == user_id)
    )).scalars().all()
    mastery_avg = round(sum(progress_rows) / len(progress_rows) * 100, 1) if progress_rows else 0.0

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
        "period": {"start": this_monday.strftime("%Y-%m-%d"), "end": now.strftime("%Y-%m-%d")},
        "this_week": this_week,
        "last_week": last_week,
        "deltas": deltas,
        "mastery_avg": mastery_avg,
        "highlights": highlights[:4],
    }
