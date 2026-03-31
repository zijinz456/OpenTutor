"""Study-related signal collectors.

Covers: active goals, deadlines, forgetting risk, prerequisite gaps.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.ingestion import Assignment
from models.progress import LearningProgress
from models.study_goal import StudyGoal

from ._types import AgendaSignal

logger = logging.getLogger(__name__)


async def _collect_active_goals(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Active study goals -- highest priority if they have a next_action or near deadline."""
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

        # urgency: next_action set -> 90, deadline <=7 days -> 85, plain goal -> 60
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

    Assignment has no user_id -- it's scoped via course_id.  When
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


async def _collect_lector_review(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """LECTOR semantic review — concepts needing review based on knowledge graph relationships."""
    if not course_id:
        return []

    try:
        from services.lector import get_smart_review_session
        items = await get_smart_review_session(db, user_id, course_id, max_items=5)
    except (SQLAlchemyError, ImportError, ConnectionError, TimeoutError):
        logger.debug("LECTOR review signal collection failed", exc_info=True)
        return []

    urgent = [i for i in items if i.priority > 0.5]
    if len(urgent) < 2:
        return []

    # Group by review type for targeted block operations
    contrast_items = [i for i in urgent if i.review_type == "contrast"]
    prereq_items = [i for i in urgent if i.review_type == "prerequisite_first"]

    signals: list[AgendaSignal] = []

    # Main LECTOR review signal
    urgency = min(70.0 + len(urgent) * 3, 88.0)
    signals.append(AgendaSignal(
        signal_type="lector_review",
        user_id=user_id,
        course_id=course_id,
        entity_id=f"lector:{course_id}",
        title=f"{len(urgent)} concepts need semantic review",
        urgency=urgency,
        detail={
            "urgent_count": len(urgent),
            "concepts": [i.concept_name for i in urgent[:5]],
            "contrast_count": len(contrast_items),
            "prereq_first_count": len(prereq_items),
            "top_reasons": [i.reason for i in urgent[:3]],
            "review_types": list({i.review_type for i in urgent}),
            "confused_concepts": [i.concept_name for i in contrast_items[:3]],
            "weak_prerequisites": [i.concept_name for i in prereq_items[:3]],
        },
    ))

    return signals


async def _collect_prerequisite_gaps(
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AgendaSignal]:
    """Detect prerequisite gaps via LOOM knowledge graph."""
    if not course_id:
        return []

    try:
        from services.loom_graph import check_prerequisite_gaps
        gaps = await check_prerequisite_gaps(db, user_id, course_id)
    except (SQLAlchemyError, ImportError, ConnectionError, TimeoutError):
        logger.exception("Prerequisite gap check failed (best-effort)")
        return []

    if not gaps:
        return []

    # Emit one signal per significant gap (severity > 0.5)
    signals: list[AgendaSignal] = []
    for gap in gaps[:5]:
        if gap["gap_severity"] < 0.5:
            continue
        urgency = min(60.0 + gap["gap_severity"] * 30, 85.0)
        signals.append(AgendaSignal(
            signal_type="prerequisite_gap",
            user_id=user_id,
            course_id=course_id,
            entity_id=gap["concept_id"],
            title=f"Prerequisite gap: {gap['concept']} (mastery {gap['mastery']:.0%})",
            urgency=urgency,
            detail={
                "concept": gap["concept"],
                "concept_id": gap["concept_id"],
                "mastery": gap["mastery"],
                "gap_severity": gap["gap_severity"],
            },
        ))
    return signals
