"""Ambient Study Monitor — LLM-enhanced proactive agent loop.

Inspired by OpenClaw Heartbeat + LangGraph Ambient Agent pattern.

The agenda service already collects signals and ranks them deterministically.
This module adds an optional LLM deliberation layer on top, which can:
1. Synthesise multiple signals into a richer decision
2. Generate personalised notification messages
3. Decide to trigger a GoalPursuit workflow when appropriate
4. Choose to remain silent when intervention would be counterproductive

The monitor is invoked by ``agenda_tick_job`` when LLM is available,
and falls back to the existing deterministic path otherwise.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.agenda_signals import AgendaSignal

logger = logging.getLogger(__name__)


def _parse_course_uuid(raw: str | None) -> uuid.UUID | None:
    """Safely parse a course_id string from LLM output into a UUID."""
    if not raw or raw in ("null", "None", "none"):
        return None
    try:
        return uuid.UUID(raw)
    except (ValueError, AttributeError):
        return None

AMBIENT_MONITOR_PROMPT = """\
You are the proactive study agent for a student using OpenTutor.
Your job is to decide what (if anything) to do based on the student's current learning state.

## Rules
- Only intervene when there is a clear benefit to the student.
- Prefer silence over spam. If the student is on track, do nothing.
- Never send more than 1 notification per 6 hours per course.
- Consider time of day: avoid actions during likely sleep hours (11pm-7am).
- For review sessions: only trigger when forgetting cost is high enough.
- For goal pursuit: only trigger when a goal has stalled for 2+ days.

## Available actions
- "silent": Do nothing. The student is on track.
- "notify": Send a motivational or reminder notification.
- "prepare_review": Queue a spaced-repetition review session.
- "trigger_goal_pursuit": Start or resume goal pursuit workflow.
- "generate_report": Generate a daily/weekly learning brief.
- "trigger_guided_session": Start a proactive guided learning session. Only trigger when the student has been studying recently, there is material to review or deadlines approaching, and no guided session was completed in the last 24 hours. This is a lower-priority action than review or goal pursuit.

## Output format
Respond with a single JSON object:
{
  "action": "<one of the above>",
  "reason": "<1-2 sentence explanation>",
  "message": "<notification text if action=notify, else empty string>",
  "priority": "<low|normal|high>",
  "target_course_id": "<course_id or null>"
}
"""


async def gather_learning_state(
    user_id: uuid.UUID,
    signals: list[AgendaSignal],
    db: AsyncSession,
) -> dict:
    """Collect a snapshot of the student's current learning state.

    Combines the agenda signals with additional context for LLM deliberation.
    """
    from models.ingestion import StudySession
    from models.progress import LearningProgress
    from models.study_goal import StudyGoal

    now = datetime.now(timezone.utc)

    # Last study session
    last_session_result = await db.execute(
        select(StudySession)
        .where(StudySession.user_id == user_id)
        .order_by(StudySession.started_at.desc())
        .limit(1)
    )
    last_session = last_session_result.scalar_one_or_none()
    hours_since_last_study = None
    if last_session and last_session.started_at:
        started = last_session.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        hours_since_last_study = (now - started).total_seconds() / 3600

    # Count overdue FSRS items
    overdue_result = await db.execute(
        select(func.count(LearningProgress.id))
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.next_review_at.isnot(None),
            LearningProgress.next_review_at <= now,
            LearningProgress.mastery_score < 0.9,
        )
    )
    overdue_count = overdue_result.scalar() or 0

    # Active goals count + stalled goals
    goals_result = await db.execute(
        select(StudyGoal)
        .where(StudyGoal.user_id == user_id, StudyGoal.status == "active")
        .limit(10)
    )
    goals = goals_result.scalars().all()
    stalled_goals = []
    for g in goals:
        updated = g.updated_at
        if updated and updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        if updated and (now - updated).days >= 2:
            stalled_goals.append({"id": str(g.id), "title": g.title, "days_stalled": (now - updated).days})

    # Serialize agenda signals
    signal_summaries = [
        {
            "type": s.signal_type,
            "title": s.title,
            "urgency": s.urgency,
            "course_id": str(s.course_id) if s.course_id else None,
        }
        for s in signals[:10]
    ]

    return {
        "current_hour": now.hour,
        "hours_since_last_study": round(hours_since_last_study, 1) if hours_since_last_study is not None else None,
        "overdue_review_items": overdue_count,
        "active_goals": len(goals),
        "stalled_goals": stalled_goals,
        "agenda_signals": signal_summaries,
    }


async def llm_deliberate(
    state: dict,
) -> dict | None:
    """Ask the LLM to decide what to do based on the learning state.

    Returns the parsed action dict, or None if LLM is unavailable/fails.
    """
    from services.llm.router import get_llm_client

    try:
        client = get_llm_client(tier="fast")
    except Exception:
        return None

    try:
        response, _ = await client.extract(
            system_prompt=AMBIENT_MONITOR_PROMPT,
            user_message=json.dumps(state, default=str),
        )

        # Parse JSON from response
        from libs.text_utils import strip_code_fences
        text = strip_code_fences(response)

        decision = json.loads(text)
        if not isinstance(decision, dict) or "action" not in decision:
            return None
        return decision

    except Exception as e:
        logger.exception("Ambient monitor LLM deliberation failed: %s", e)
        return None


async def execute_ambient_decision(
    user_id: uuid.UUID,
    decision: dict,
    db: AsyncSession,
) -> str:
    """Execute the LLM's decision.

    Returns a status string for logging.
    """
    action = decision.get("action", "silent")

    if action == "silent":
        return "silent"

    elif action == "notify":
        logger.debug("Notification skipped (removed): %s", decision.get("message", ""))
        return "notify_skipped"

    elif action == "prepare_review":
        from services.activity.engine import submit_task
        from models.agent_task import AgentTask
        course_uuid = _parse_course_uuid(decision.get("target_course_id"))

        # Skip if a review task is already queued/running (cross-job dedup)
        active_review = await db.execute(
            select(AgentTask.id)
            .where(
                AgentTask.user_id == user_id,
                AgentTask.task_type == "review_session",
                AgentTask.status.in_(("queued", "running", "pending_approval")),
            )
            .limit(1)
        )
        if active_review.scalar_one_or_none() is not None:
            return "review_already_queued"

        await submit_task(
            user_id=user_id,
            course_id=course_uuid,
            task_type="review_session",
            title="Proactive review session",
            summary=decision.get("reason", "Agent-initiated review based on forgetting risk"),
            source="ambient_monitor",
            input_json={
                "session_kind": "due_review",
                "trigger_signal": "ambient_monitor",
            },
            requires_approval=False,
            max_attempts=2,
        )
        return "review_queued"

    elif action == "trigger_goal_pursuit":
        from models.study_goal import StudyGoal
        from services.activity.engine import submit_task
        # Find the most stalled goal
        stalled = await db.execute(
            select(StudyGoal)
            .where(StudyGoal.user_id == user_id, StudyGoal.status == "active")
            .order_by(StudyGoal.updated_at.asc())
            .limit(1)
        )
        goal = stalled.scalar_one_or_none()
        if goal:
            # Queue as async task instead of running synchronously in the scheduler
            await submit_task(
                user_id=user_id,
                goal_id=goal.id,
                course_id=goal.course_id,
                task_type="goal_pursuit",
                title=f"Resume goal: {goal.title}",
                summary=decision.get("reason", "Agent-initiated goal pursuit"),
                source="ambient_monitor",
                input_json={
                    "goal_id": str(goal.id),
                    "goal_title": goal.title,
                    "goal_objective": goal.objective or "",
                },
                requires_approval=False,
                max_attempts=2,
            )
            return "goal_pursuit_queued"
        return "no_goal_found"

    elif action == "generate_report":
        from services.activity.engine import submit_task
        await submit_task(
            user_id=user_id,
            task_type="daily_brief",
            title="Daily learning brief",
            summary="Agent-generated learning status report",
            source="ambient_monitor",
            input_json={"trigger": "ambient_monitor"},
            requires_approval=False,
            max_attempts=1,
        )
        return "report_queued"

    elif action == "trigger_guided_session":
        from services.activity.engine import submit_task
        from models.agent_task import AgentTask

        # Skip if a guided session task is already queued/running
        active_session = await db.execute(
            select(AgentTask.id)
            .where(
                AgentTask.user_id == user_id,
                AgentTask.task_type == "guided_session",
                AgentTask.status.in_(("queued", "running", "pending_approval")),
            )
            .limit(1)
        )
        if active_session.scalar_one_or_none() is not None:
            return "guided_session_already_queued"

        course_uuid = _parse_course_uuid(decision.get("target_course_id"))
        await submit_task(
            user_id=user_id,
            course_id=course_uuid,
            task_type="guided_session",
            title="Guided study session",
            summary=decision.get("reason", "Agent-initiated guided learning session"),
            source="ambient_monitor",
            input_json={
                "course_id": str(course_uuid) if course_uuid else None,
                "trigger": "ambient_monitor",
            },
            requires_approval=False,
            max_attempts=1,
        )
        return "guided_session_queued"

    return "unknown_action"
