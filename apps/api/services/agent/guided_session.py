"""Guided Study Session — proactive structured learning orchestrator.

Implements a 4-phase learning loop that delegates to existing specialist agents:
1. Warm-up Review   (ReviewAgent)  — 2-3 FSRS overdue items
2. New Concept Teach (TeachingAgent) — deadline-prioritised topic
3. Practice         (ExerciseAgent) — 2-4 adaptive problems
4. Summary          (TeachingAgent) — recap + flashcard prompt

State is persisted in AgentKV (namespace="guided_session") so sessions
can be paused and resumed across requests.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.agent.kv_store import kv_get, kv_set

logger = logging.getLogger(__name__)

PHASES = ("warmup", "teach", "practice", "summary")


# ---------------------------------------------------------------------------
# Topic selection
# ---------------------------------------------------------------------------

async def select_session_topic(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID | None,
) -> dict:
    """Pick the best topic for a guided session.

    Priority order:
    1. Deadline-driven — assignment due within 7 days
    2. Lowest mastery — weakest LearningProgress entry
    3. Curriculum order — next unvisited ContentNode
    """
    from models.ingestion import Assignment
    from models.progress import LearningProgress
    from models.content import CourseContentTree

    now = datetime.now(timezone.utc)

    # --- Priority 1: Upcoming deadline ---
    deadline_q = (
        select(Assignment)
        .where(
            Assignment.status == "active",
            Assignment.due_date.isnot(None),
            Assignment.due_date <= now + timedelta(days=7),
            Assignment.due_date >= now,
        )
    )
    if course_id:
        deadline_q = deadline_q.where(Assignment.course_id == course_id)
    deadline_q = deadline_q.order_by(Assignment.due_date.asc()).limit(1)
    result = await db.execute(deadline_q)
    deadline_assignment = result.scalar_one_or_none()

    if deadline_assignment:
        days_left = max(int((deadline_assignment.due_date - now).total_seconds() // 86400), 0)
        return {
            "source": "deadline",
            "title": deadline_assignment.title,
            "course_id": str(deadline_assignment.course_id),
            "assignment_id": str(deadline_assignment.id),
            "days_until_due": days_left,
            "assignment_type": deadline_assignment.assignment_type,
        }

    # --- Priority 2: Lowest mastery ---
    mastery_q = (
        select(LearningProgress)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.mastery_score < 0.7,
        )
    )
    if course_id:
        mastery_q = mastery_q.where(LearningProgress.course_id == course_id)
    mastery_q = mastery_q.order_by(LearningProgress.mastery_score.asc()).limit(1)
    result = await db.execute(mastery_q)
    weak_item = result.scalar_one_or_none()

    if weak_item:
        return {
            "source": "low_mastery",
            "title": str(weak_item.content_node_id or "Weak area review"),
            "course_id": str(weak_item.course_id) if weak_item.course_id else None,
            "content_node_id": str(weak_item.content_node_id) if weak_item.content_node_id else None,
            "mastery_score": float(weak_item.mastery_score) if weak_item.mastery_score else 0,
        }

    # --- Priority 3: Next curriculum node ---
    if course_id:
        node_q = (
            select(CourseContentTree)
            .where(CourseContentTree.course_id == course_id)
            .order_by(CourseContentTree.sort_order.asc())
            .limit(1)
        )
        result = await db.execute(node_q)
        node = result.scalar_one_or_none()
        if node:
            return {
                "source": "curriculum",
                "title": node.title or "Next topic",
                "course_id": str(course_id),
                "content_node_id": str(node.id),
            }

    return {"source": "general", "title": "General review"}


# ---------------------------------------------------------------------------
# Phase prompt builders
# ---------------------------------------------------------------------------

def build_phase_prompt(phase: str, topic: dict, session_state: dict) -> str:
    """Build a system prompt segment for the current guided session phase."""
    topic_title = topic.get("title", "the current topic")
    deadline_ctx = ""
    if topic.get("source") == "deadline":
        days = topic.get("days_until_due", "?")
        deadline_ctx = f"\n\nIMPORTANT: This topic has a deadline in {days} days. Focus on exam/assignment preparation."

    if phase == "warmup":
        return (
            f"[GUIDED SESSION — WARM-UP REVIEW]\n"
            f"Topic context: {topic_title}{deadline_ctx}\n\n"
            f"Generate 2-3 quick recall questions based on the student's previously studied material. "
            f"These should be short, factual questions to activate prior knowledge. "
            f"After each answer, give brief feedback. Keep this phase under 3 minutes."
        )
    elif phase == "teach":
        return (
            f"[GUIDED SESSION — NEW CONCEPT]\n"
            f"Topic: {topic_title}{deadline_ctx}\n\n"
            f"Teach the student about this topic using clear explanations, examples, and analogies. "
            f"Break down complex ideas into digestible parts. "
            f"Check understanding with 1-2 comprehension questions mid-explanation. "
            f"Target 5-10 minutes of instruction."
        )
    elif phase == "practice":
        warmup_score = session_state.get("performance_warmup")
        difficulty_hint = ""
        if warmup_score is not None and warmup_score < 0.3:
            difficulty_hint = " Start with easier, foundational questions since the warm-up showed gaps."
        elif warmup_score is not None and warmup_score > 0.8:
            difficulty_hint = " The student performed well in warm-up — use challenging application questions."
        return (
            f"[GUIDED SESSION — PRACTICE]\n"
            f"Topic: {topic_title}{deadline_ctx}\n\n"
            f"Create 2-4 practice problems for the student on this topic.{difficulty_hint} "
            f"Vary difficulty progressively. After each answer, provide detailed feedback. "
            f"If the student gets >80% correct, offer a bonus challenge problem."
        )
    elif phase == "summary":
        practice_results = session_state.get("practice_results", [])
        correct = sum(1 for r in practice_results if r.get("correct"))
        total = len(practice_results) if practice_results else 0
        return (
            f"[GUIDED SESSION — SUMMARY]\n"
            f"Topic: {topic_title}\n"
            f"Practice results: {correct}/{total} correct\n\n"
            f"Summarise the key points covered in this session. "
            f"Highlight what the student did well and areas for improvement. "
            f"Suggest what to study next. "
            f"Offer to create flashcards for the key concepts using [ACTION:create_flashcards]."
        )
    return ""


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def _session_key(task_id: str) -> str:
    return f"session:{task_id}"


async def prepare_guided_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    payload: dict,
) -> dict:
    """Prepare a guided session — select topic, initialise state, store in KV.

    Called by the activity engine when a guided_session task is dispatched.
    Returns a result dict for the task system.
    """
    course_id_str = payload.get("course_id")
    course_id = uuid.UUID(course_id_str) if course_id_str else None
    task_id = payload.get("task_id", str(uuid.uuid4()))

    topic = await select_session_topic(db, user_id, course_id)

    session_state = {
        "task_id": task_id,
        "status": "prepared",
        "current_phase": "warmup",
        "phase_index": 0,
        "topic": topic,
        "course_id": str(course_id) if course_id else topic.get("course_id"),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "performance_warmup": None,
        "practice_results": [],
        "completed_phases": [],
    }

    await kv_set(db, user_id, "guided_session", _session_key(task_id), session_state)

    return {
        "success": True,
        "task_id": task_id,
        "topic": topic,
        "summary": f"Guided session prepared: {topic.get('title', 'General review')}",
    }


async def get_session_state(
    db: AsyncSession,
    user_id: uuid.UUID,
    task_id: str,
) -> dict | None:
    """Load guided session state from KV store."""
    return await kv_get(db, user_id, "guided_session", _session_key(task_id))


async def advance_phase(
    db: AsyncSession,
    user_id: uuid.UUID,
    task_id: str,
    phase_result: dict | None = None,
) -> dict:
    """Move to the next phase. Returns updated session state.

    ``phase_result`` may contain performance data from the just-finished phase.
    """
    state = await get_session_state(db, user_id, task_id)
    if not state:
        return {"error": "session_not_found"}

    current = state["current_phase"]
    state["completed_phases"].append(current)

    # Record performance from completed phase
    if phase_result:
        if current == "warmup":
            state["performance_warmup"] = phase_result.get("score")
        elif current == "practice":
            state["practice_results"] = phase_result.get("results", [])

    # Determine next phase
    idx = state["phase_index"] + 1

    # Mid-session adaptation
    adapted = adapt_session(state)
    if adapted:
        state["current_phase"] = adapted
        idx = PHASES.index(adapted)
    elif idx < len(PHASES):
        state["current_phase"] = PHASES[idx]
    else:
        state["current_phase"] = "completed"
        state["status"] = "completed"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()

    state["phase_index"] = idx
    if state["status"] != "completed":
        state["status"] = "active"

    await kv_set(db, user_id, "guided_session", _session_key(task_id), state)
    return state


def adapt_session(state: dict) -> str | None:
    """Check if mid-session adaptation is needed. Returns new phase or None."""
    current = state["current_phase"]
    warmup_score = state.get("performance_warmup")

    # After warmup: if score < 0.3, skip teach and go to practice (reinforce fundamentals)
    if current == "warmup" and warmup_score is not None and warmup_score < 0.3:
        return "practice"

    # After practice: if accuracy > 80%, skip to summary
    practice = state.get("practice_results", [])
    if current == "practice" and practice:
        correct = sum(1 for r in practice if r.get("correct"))
        if len(practice) >= 3 and correct / len(practice) > 0.8:
            # Good performance — can proceed to summary early
            return None  # let normal flow continue

    return None


async def pause_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    task_id: str,
) -> dict:
    """Pause a session for later resumption."""
    state = await get_session_state(db, user_id, task_id)
    if not state:
        return {"error": "session_not_found"}

    state["status"] = "paused"
    state["paused_at"] = datetime.now(timezone.utc).isoformat()
    await kv_set(db, user_id, "guided_session", _session_key(task_id), state)
    return state


async def resume_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    task_id: str,
) -> dict:
    """Resume a paused session."""
    state = await get_session_state(db, user_id, task_id)
    if not state:
        return {"error": "session_not_found"}

    if state["status"] != "paused":
        return state  # already active or completed

    state["status"] = "active"
    state["resumed_at"] = datetime.now(timezone.utc).isoformat()
    await kv_set(db, user_id, "guided_session", _session_key(task_id), state)
    return state
