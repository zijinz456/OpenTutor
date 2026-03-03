"""Agenda signal collectors.

Each collector queries one data source and returns zero or more AgendaSignal
instances.  The agenda service calls ``collect_signals`` which fans out to
all collectors and returns a flat list.
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent_task import AgentTask
from models.ingestion import Assignment, StudySession, WrongAnswer
from models.progress import LearningProgress
from models.study_goal import StudyGoal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

SIGNAL_TYPES = (
    "active_goal",
    "deadline",
    "failed_task",
    "forgetting_risk",
    "weak_area",
    "inactivity",
)


@dataclass
class AgendaSignal:
    """A single signal for the agenda ranker."""

    signal_type: str          # one of SIGNAL_TYPES
    user_id: uuid.UUID
    course_id: uuid.UUID | None = None
    entity_id: str | None = None       # goal_id, task_id, assignment_id, etc.
    title: str = ""
    urgency: float = 0.0              # 0-100 normalised priority score
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual collectors
# ---------------------------------------------------------------------------

async def _collect_active_goals(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Active study goals — highest priority if they have a next_action or near deadline."""
    query = (
        select(StudyGoal)
        .where(StudyGoal.user_id == user_id, StudyGoal.status == "active")
    )
    if course_id:
        query = query.where(StudyGoal.course_id == course_id)
    query = query.order_by(StudyGoal.updated_at.desc()).limit(5)
    result = await db.execute(query)
    goals = result.scalars().all()

    signals: list[AgendaSignal] = []
    now = datetime.now(timezone.utc)
    for goal in goals:
        days_left = None
        if goal.target_date:
            target = goal.target_date if goal.target_date.tzinfo else goal.target_date.replace(tzinfo=timezone.utc)
            days_left = max(int((target - now).total_seconds() // 86400), 0)

        # urgency: next_action set → 90, deadline ≤7 days → 85, plain goal → 60
        if goal.next_action:
            urgency = 90.0
        elif days_left is not None and days_left <= 7:
            urgency = 85.0
        else:
            urgency = 60.0

        signals.append(AgendaSignal(
            signal_type="active_goal",
            user_id=user_id,
            course_id=goal.course_id,
            entity_id=str(goal.id),
            title=goal.title,
            urgency=urgency,
            detail={
                "next_action": goal.next_action,
                "days_until_target": days_left,
                "objective": goal.objective,
                "has_next_action": bool(goal.next_action),
            },
        ))
    return signals


async def _collect_deadlines(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Assignments due within 7 days.

    Assignment has no user_id — it's scoped via course_id.  When
    course_id is None (cross-course tick), we first resolve the user's
    course IDs to avoid leaking other users' assignments.
    """
    from models.course import Course

    now = datetime.now(timezone.utc)
    query = select(Assignment).where(
        Assignment.status == "active",
        Assignment.due_date.isnot(None),
        Assignment.due_date <= now + timedelta(days=7),
        Assignment.due_date >= now - timedelta(hours=1),
    )
    if course_id:
        query = query.where(Assignment.course_id == course_id)
    else:
        # Scope to courses owned by this user
        user_courses = select(Course.id).where(Course.user_id == user_id)
        query = query.where(Assignment.course_id.in_(user_courses))
    query = query.order_by(Assignment.due_date.asc()).limit(5)
    result = await db.execute(query)
    assignments = result.scalars().all()

    signals: list[AgendaSignal] = []
    for a in assignments:
        target = a.due_date if a.due_date.tzinfo else a.due_date.replace(tzinfo=timezone.utc)
        days_left = max(int((target - now).total_seconds() // 86400), 0)
        urgency = max(95.0 - days_left * 5, 70.0)
        signals.append(AgendaSignal(
            signal_type="deadline",
            user_id=user_id,
            course_id=a.course_id,
            entity_id=str(a.id),
            title=a.title,
            urgency=urgency,
            detail={"days_until_due": days_left, "assignment_type": a.assignment_type},
        ))
    return signals


async def _collect_failed_tasks(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Most recent failed/cancelled/rejected tasks (recovery candidates)."""
    query = (
        select(AgentTask)
        .where(
            AgentTask.user_id == user_id,
            AgentTask.status.in_(("failed", "cancelled", "rejected")),
        )
    )
    if course_id:
        query = query.where(AgentTask.course_id == course_id)
    query = query.order_by(AgentTask.updated_at.desc()).limit(3)
    result = await db.execute(query)
    tasks = result.scalars().all()

    return [
        AgendaSignal(
            signal_type="failed_task",
            user_id=user_id,
            course_id=t.course_id,
            entity_id=str(t.id),
            title=t.title,
            urgency=80.0,
            detail={"status": t.status, "task_type": t.task_type, "error": t.error_message},
        )
        for t in tasks
    ]


async def _collect_forgetting_risk(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Knowledge points overdue for FSRS review."""
    now = datetime.now(timezone.utc)
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
    query = query.order_by(LearningProgress.next_review_at.asc()).limit(10)
    result = await db.execute(query)
    items = result.scalars().all()

    if not items:
        return []

    # Aggregate into one signal per course, with forgetting cost estimation
    from services.spaced_repetition.fsrs import FSRSCard, estimate_forgetting_cost

    by_course: dict[uuid.UUID | None, list] = {}
    for item in items:
        by_course.setdefault(item.course_id, []).append(item)

    signals: list[AgendaSignal] = []
    for cid, group in by_course.items():
        overdue_count = len(group)

        # Build FSRSCard objects for forgetting cost estimation (Orbit-inspired)
        cards = []
        for i in group:
            due_at = i.next_review_at
            if due_at and due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            # Use real FSRS stability from the model (falls back to 1.0 for new cards)
            stability = float(i.fsrs_stability) if i.fsrs_stability and i.fsrs_stability > 0 else 1.0
            cards.append(FSRSCard(
                stability=stability,
                due=due_at,
            ))
        forgetting_cost = estimate_forgetting_cost(cards, now)

        # Urgency now factors in forgetting cost
        if forgetting_cost >= 5.0:
            urgency = 92.0  # Critical
        elif forgetting_cost >= 2.0:
            urgency = min(75.0 + forgetting_cost * 3, 90.0)
        else:
            urgency = min(70.0 + overdue_count * 3, 88.0)

        signals.append(AgendaSignal(
            signal_type="forgetting_risk",
            user_id=user_id,
            course_id=cid,
            entity_id=f"fsrs:{cid or 'all'}",
            title=f"{overdue_count} items overdue (cost={forgetting_cost:.1f})",
            urgency=urgency,
            detail={
                "overdue_count": overdue_count,
                "forgetting_cost": forgetting_cost,
                "items": [
                    {
                        "content_node_id": str(i.content_node_id) if i.content_node_id else None,
                        "title": str(i.content_node_id or "unknown"),
                        "mastery_score": float(i.mastery_score) if i.mastery_score else 0,
                    }
                    for i in group[:5]
                ],
            },
        ))
    return signals


async def _collect_weak_areas(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Courses with ≥3 unmastered wrong answers."""
    query = (
        select(WrongAnswer.course_id, func.count(WrongAnswer.id).label("cnt"))
        .where(WrongAnswer.user_id == user_id, WrongAnswer.mastered.is_(False))
    )
    if course_id:
        query = query.where(WrongAnswer.course_id == course_id)
    query = query.group_by(WrongAnswer.course_id)
    result = await db.execute(query)

    signals: list[AgendaSignal] = []
    for cid, cnt in result.all():
        if cnt < 3:
            continue
        signals.append(AgendaSignal(
            signal_type="weak_area",
            user_id=user_id,
            course_id=cid,
            entity_id=f"weak:{cid}",
            title=f"{cnt} unmastered wrong answers",
            urgency=min(55.0 + cnt * 2, 75.0),
            detail={"unmastered_count": cnt},
        ))
    return signals


async def _collect_inactivity(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Detect if the user has been inactive for ≥3 days."""
    threshold = datetime.now(timezone.utc) - timedelta(days=3)
    query = (
        select(StudySession)
        .where(StudySession.user_id == user_id)
        .order_by(StudySession.started_at.desc())
        .limit(1)
    )
    result = await db.execute(query)
    last = result.scalar_one_or_none()

    if last and last.started_at and last.started_at < threshold:
        days_inactive = (datetime.now(timezone.utc) - last.started_at).days
        return [AgendaSignal(
            signal_type="inactivity",
            user_id=user_id,
            course_id=None,
            entity_id=f"inactivity:{user_id}",
            title=f"Inactive for {days_inactive} days",
            urgency=min(40.0 + days_inactive * 5, 65.0),
            detail={"days_inactive": days_inactive, "last_session": last.started_at.isoformat()},
        )]
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_COLLECTORS = [
    _collect_active_goals,
    _collect_deadlines,
    _collect_failed_tasks,
    _collect_forgetting_risk,
    _collect_weak_areas,
    _collect_inactivity,
]


async def collect_signals(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    db: AsyncSession | None = None,
) -> list[AgendaSignal]:
    """Run all signal collectors concurrently and return a flat list of signals."""
    if db is None:
        raise ValueError("db session is required")

    import asyncio

    async def _safe_collect(collector) -> list[AgendaSignal]:
        try:
            return await collector(user_id, course_id, db)
        except Exception:
            logger.exception("Signal collector %s failed", collector.__name__)
            return []

    results = await asyncio.gather(*[_safe_collect(c) for c in _COLLECTORS])
    return [signal for batch in results for signal in batch]
