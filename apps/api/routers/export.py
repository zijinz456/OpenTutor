"""Data export endpoints — session transcript, Anki deck, and calendar ICS."""

import csv
import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.chat_message import ChatMessageLog
from models.chat_session import ChatSession
from models.course import Course
from models.practice import PracticeProblem
from models.study_goal import StudyGoal
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404

router = APIRouter()


# ── Session export (CSV transcript of all chat messages) ──


@router.get("/export/session")
async def export_session(
    course_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export chat session history as CSV."""
    query = (
        select(
            ChatSession.course_id,
            ChatSession.title,
            ChatMessageLog.role,
            ChatMessageLog.content,
            ChatMessageLog.created_at,
        )
        .join(ChatMessageLog, ChatMessageLog.session_id == ChatSession.id)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatMessageLog.created_at)
    )
    if course_id:
        query = query.where(ChatSession.course_id == course_id)

    result = await db.execute(query)
    rows = result.all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["course_id", "session_title", "role", "content", "timestamp"])
    for row in rows:
        writer.writerow([
            str(row.course_id),
            row.title or "",
            row.role,
            row.content,
            row.created_at.isoformat() if row.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=opentutor-session-export.csv"},
    )


# ── Anki export (tab-separated text for Anki import) ──


@router.get("/export/anki")
async def export_anki(
    course_id: uuid.UUID,
    batch_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export practice problems as Anki-compatible tab-separated file."""
    await get_course_or_404(db, course_id, user_id=user.id)

    query = (
        select(PracticeProblem)
        .where(
            PracticeProblem.course_id == course_id,
            PracticeProblem.is_archived == False,  # noqa: E712
        )
        .order_by(PracticeProblem.order_index)
    )
    if batch_id:
        query = query.where(PracticeProblem.source_batch_id == batch_id)

    result = await db.execute(query)
    problems = result.scalars().all()

    output = io.StringIO()
    for p in problems:
        front = p.question or ""
        # Build back from correct answer + explanation
        back_parts = []
        if p.correct_answer:
            back_parts.append(p.correct_answer)
        if p.explanation:
            back_parts.append(p.explanation)
        back = "\n".join(back_parts) if back_parts else "—"
        # Anki uses tab-separated: front\tback
        output.write(f"{front}\t{back}\n")

    output.seek(0)

    # Get course name for filename
    course_result = await db.execute(select(Course.name).where(Course.id == course_id))
    course_name = course_result.scalar() or "opentutor"
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in course_name).strip()

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={safe_name}-anki.txt"},
    )


# ── Calendar export (ICS format for study goal deadlines) ──


@router.get("/export/calendar")
async def export_calendar(
    course_id: uuid.UUID,
    plan_batch_id: uuid.UUID | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export study goal deadlines as ICS calendar file."""
    query = (
        select(StudyGoal)
        .where(
            StudyGoal.user_id == user.id,
            StudyGoal.course_id == course_id,
            StudyGoal.target_date.isnot(None),
        )
        .order_by(StudyGoal.target_date)
    )
    if plan_batch_id:
        query = query.where(StudyGoal.metadata_json["plan_batch_id"].as_string() == str(plan_batch_id))

    result = await db.execute(query)
    goals = result.scalars().all()

    # Get course name
    course_result = await db.execute(select(Course.name).where(Course.id == course_id))
    course_name = course_result.scalar() or "OpenTutor"

    # Build ICS
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//OpenTutor//Study Goals//EN",
        f"X-WR-CALNAME:{course_name} Study Goals",
    ]
    for goal in goals:
        dt = goal.target_date
        if not dt:
            continue
        dtstr = dt.strftime("%Y%m%d")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{goal.id}@opentutor",
            f"DTSTAMP:{now}",
            f"DTSTART;VALUE=DATE:{dtstr}",
            f"DTEND;VALUE=DATE:{dtstr}",
            f"SUMMARY:{goal.title}",
            f"DESCRIPTION:{goal.objective or ''}",
            f"STATUS:{'COMPLETED' if goal.status == 'completed' else 'CONFIRMED'}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")

    ics_content = "\r\n".join(lines)
    safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in course_name).strip()

    return StreamingResponse(
        iter([ics_content]),
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename={safe_name}-goals.ics"},
    )
