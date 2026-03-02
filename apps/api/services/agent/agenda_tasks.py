"""Agenda-driven task implementations.

These are the actual "do the work" functions for task types created
by the agenda service:

- ``review_session``   — FSRS-driven spaced repetition review
- ``reentry_session``  — low-friction re-entry after inactivity
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import StudySession, WrongAnswer
from models.progress import LearningProgress
from models.study_goal import StudyGoal

logger = logging.getLogger(__name__)

JsonObject = dict


async def run_review_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: JsonObject,
) -> JsonObject:
    """Execute a review_session task.

    Gathers overdue FSRS items + related wrong answers and returns a
    structured review package.  Does NOT call the LLM — the first version
    is pure data retrieval so it's cheap and fast.
    """
    course_id = _uuid(payload.get("course_id"))
    duration_minutes = int(payload.get("duration_minutes", 10))
    now = datetime.now(timezone.utc)

    # 1. Overdue FSRS items
    query = (
        select(LearningProgress)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.next_review_at.isnot(None),
            LearningProgress.next_review_at <= now,
            LearningProgress.mastery_score < 0.9,
        )
    )
    if course_id:
        query = query.where(LearningProgress.course_id == course_id)
    query = query.order_by(LearningProgress.next_review_at.asc()).limit(20)
    result = await db.execute(query)
    overdue_items = result.scalars().all()

    # 2. Related wrong answers (recent, unmastered)
    wa_query = (
        select(WrongAnswer)
        .where(WrongAnswer.user_id == user_id, WrongAnswer.mastered.is_(False))
    )
    if course_id:
        wa_query = wa_query.where(WrongAnswer.course_id == course_id)
    wa_query = wa_query.order_by(WrongAnswer.created_at.desc()).limit(10)
    wa_result = await db.execute(wa_query)
    wrong_answers = wa_result.scalars().all()

    # 3. Build review package
    review_items = [
        {
            "content_node_id": str(item.content_node_id) if item.content_node_id else None,
            "title": getattr(item, "title", None) or str(item.content_node_id or ""),
            "mastery_score": float(item.mastery_score) if item.mastery_score else 0,
            "next_review_at": item.next_review_at.isoformat() if item.next_review_at else None,
            "urgency": _classify_urgency(item, now),
        }
        for item in overdue_items
    ]

    wrong_answer_items = [
        {
            "id": str(wa.id),
            "user_answer": wa.user_answer[:200] if wa.user_answer else "",
            "correct_answer": (wa.correct_answer or "")[:200],
            "error_category": wa.error_category,
            "review_count": wa.review_count,
        }
        for wa in wrong_answers
    ]

    summary = (
        f"Review session: {len(review_items)} overdue items, "
        f"{len(wrong_answer_items)} wrong answers. "
        f"Suggested duration: {duration_minutes} min."
    )

    return {
        "session_kind": payload.get("session_kind", "due_review"),
        "trigger_signal": payload.get("trigger_signal", "forgetting_risk"),
        "course_id": str(course_id) if course_id else None,
        "duration_minutes": duration_minutes,
        "review_items": review_items,
        "wrong_answers": wrong_answer_items,
        "total_overdue": len(review_items),
        "total_wrong_answers": len(wrong_answer_items),
        "summary": summary,
        "entry_prompt": payload.get(
            "entry_prompt",
            "Review these topics before they fade from memory.",
        ),
    }


async def run_reentry_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: JsonObject,
) -> JsonObject:
    """Execute a reentry_session task.

    Prepares a low-friction restart for a user who has been inactive.
    Finds their last session, most recent active goal, and suggests
    the easiest next step.
    """
    days_inactive = int(payload.get("days_inactive", 3))
    now = datetime.now(timezone.utc)

    # 1. Last study session
    sess_result = await db.execute(
        select(StudySession)
        .where(StudySession.user_id == user_id)
        .order_by(StudySession.started_at.desc())
        .limit(1)
    )
    last_session = sess_result.scalar_one_or_none()

    # 2. Most recent active goal
    goal_result = await db.execute(
        select(StudyGoal)
        .where(StudyGoal.user_id == user_id, StudyGoal.status == "active")
        .order_by(StudyGoal.updated_at.desc())
        .limit(1)
    )
    active_goal = goal_result.scalar_one_or_none()

    # 3. Low-mastery items (easy wins)
    lp_result = await db.execute(
        select(LearningProgress)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.mastery_score > 0.3,
            LearningProgress.mastery_score < 0.7,
        )
        .order_by(LearningProgress.mastery_score.asc())
        .limit(5)
    )
    medium_items = lp_result.scalars().all()

    # 4. Build re-entry package
    suggested_duration = min(5 + days_inactive, 15)

    summary_parts = [f"Welcome back after {days_inactive} days."]
    if active_goal:
        summary_parts.append(f"Your active goal: {active_goal.title}.")
    if medium_items:
        summary_parts.append(f"{len(medium_items)} topics at medium mastery — good for a quick refresh.")
    summary_parts.append(f"Suggested session: {suggested_duration} minutes.")

    return {
        "trigger_signal": "inactivity",
        "days_inactive": days_inactive,
        "suggested_duration_minutes": suggested_duration,
        "last_session": {
            "started_at": last_session.started_at.isoformat() if last_session and last_session.started_at else None,
            "course_id": str(last_session.course_id) if last_session else None,
        } if last_session else None,
        "active_goal": {
            "id": str(active_goal.id),
            "title": active_goal.title,
            "next_action": active_goal.next_action,
        } if active_goal else None,
        "easy_win_items": [
            {
                "content_node_id": str(item.content_node_id) if item.content_node_id else None,
                "mastery_score": float(item.mastery_score) if item.mastery_score else 0,
            }
            for item in medium_items
        ],
        "summary": " ".join(summary_parts),
        "entry_prompt": (
            f"You've been away for {days_inactive} days. "
            f"Let's start with a quick {suggested_duration}-minute session to get back on track."
        ),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid(value) -> uuid.UUID | None:
    if not value:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _classify_urgency(item: LearningProgress, now: datetime) -> str:
    if not item.next_review_at:
        return "ok"
    review_at = item.next_review_at
    if review_at.tzinfo is None:
        review_at = review_at.replace(tzinfo=timezone.utc)
    delta = now - review_at
    if delta > timedelta(days=7):
        return "overdue"
    if delta > timedelta(days=2):
        return "urgent"
    if delta > timedelta(hours=0):
        return "warning"
    return "ok"
