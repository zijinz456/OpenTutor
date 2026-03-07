"""Deterministic agenda ranking and deduplication.

Priority order (descending):
1. failed_task recovery              (urgency ≥ 80)
2. active_goal with due date ≤ 7d   (urgency ≥ 85)
3. deadline (assignment) ≤ 7d       (urgency ≥ 70)
4. active_goal with next_action     (urgency ≥ 90 but ranked after deadline)
5. forgetting_risk overdue           (urgency ≥ 70)
6. weak_area review                  (urgency ≥ 55)
7. active_goal (generic)             (urgency ≥ 60)
8. inactivity re-entry               (urgency ≥ 40)

The ranker does NOT call the LLM — it is purely deterministic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.agent.agenda_signals import AgendaSignal

# Precedence weight by signal type.  Higher = more important.
_TYPE_PRECEDENCE: dict[str, int] = {
    "failed_task": 100,
    "deadline": 90,
    "active_goal": 80,      # sub-ranked by urgency
    "prerequisite_gap": 75,  # between forgetting_risk and active_goal
    "forgetting_risk": 70,
    "weak_area": 50,
    "content_stale": 48,
    "guided_session_ready": 45,
    "inactivity": 30,
}


@dataclass
class AgendaDecision:
    """The output of the ranker: what the agent should do right now."""

    # "noop" | "submit" | "resume" | "retry" | "notify_only"
    action: str = "noop"

    # Winning signal (None for noop)
    signal: AgendaSignal | None = None

    # Task parameters (populated by agenda.py when materializing)
    task_type: str | None = None
    task_title: str | None = None
    task_summary: str | None = None
    input_json: dict = field(default_factory=dict)
    goal_id: uuid.UUID | None = None
    existing_task_id: uuid.UUID | None = None
    plan_prompt: str | None = None

    # Dedup key for this decision
    dedup_key: str | None = None

    # Why was this decision made (human-readable)
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "signal_type": self.signal.signal_type if self.signal else None,
            "task_type": self.task_type,
            "task_title": self.task_title,
            "dedup_key": self.dedup_key,
            "reason": self.reason,
            "goal_id": str(self.goal_id) if self.goal_id else None,
            "existing_task_id": str(self.existing_task_id) if self.existing_task_id else None,
        }


def _sort_key(signal: AgendaSignal) -> tuple:
    """Sort key: higher precedence first, then higher urgency first."""
    return (-_TYPE_PRECEDENCE.get(signal.signal_type, 0), -signal.urgency)


def rank_signals(signals: list[AgendaSignal]) -> AgendaDecision:
    """Pick the single best action from a list of signals.

    Returns a decision with ``action="noop"`` if no actionable signal exists.
    """
    if not signals:
        return AgendaDecision(action="noop", reason="No signals collected.")

    ranked = sorted(signals, key=_sort_key)
    winner = ranked[0]

    decision = AgendaDecision(signal=winner)

    now = datetime.now(timezone.utc)
    date_bucket = now.strftime("%Y-%m-%d")
    base_dedup = f"{winner.user_id}:{winner.course_id or 'all'}:{winner.signal_type}:{winner.entity_id}:{date_bucket}"
    decision.dedup_key = base_dedup

    if winner.signal_type == "failed_task":
        is_cancelled = winner.detail.get("status") == "cancelled"
        decision.action = "resume" if is_cancelled else "retry"
        decision.existing_task_id = uuid.UUID(winner.entity_id) if winner.entity_id else None
        decision.task_type = winner.detail.get("task_type")
        decision.task_title = f"Recover: {winner.title}"
        decision.reason = "Most recent durable task did not finish; recovery is more valuable than starting new work."

    elif winner.signal_type == "active_goal":
        detail = winner.detail
        decision.action = "submit"
        decision.goal_id = uuid.UUID(winner.entity_id) if winner.entity_id else None

        if detail.get("has_next_action"):
            decision.task_type = "multi_step"
            decision.task_title = f"Execute next step: {winner.title}"
            decision.task_summary = detail.get("next_action", "")
            decision.plan_prompt = (
                f"Goal: {winner.title}\n"
                f"Objective: {detail.get('objective', '')}\n"
                f"Immediate next action: {detail.get('next_action', '')}"
            )
            decision.reason = "Active goal has a concrete next action."
        elif (detail.get("days_until_target") or 999) <= 7:
            decision.task_type = "exam_prep"
            decision.task_title = f"Exam prep: {winner.title}"
            decision.task_summary = f"Break {winner.title} into a plan for the next 7 days."
            decision.input_json = {
                "course_id": str(winner.course_id) if winner.course_id else None,
                "exam_topic": winner.title,
                "days_until_exam": max(detail.get("days_until_target", 7), 1),
            }
            decision.reason = f"Goal due in {detail.get('days_until_target')} day(s)."
        else:
            decision.task_type = "multi_step"
            decision.task_title = f"Plan next step: {winner.title}"
            decision.task_summary = f"Turn {winner.title} into a concrete study task."
            decision.plan_prompt = (
                f"Goal: {winner.title}\n"
                f"Objective: {detail.get('objective', '')}\n"
                f"Requested: convert to next executable step."
            )
            decision.reason = "Active goal needs conversion to an executable step."

    elif winner.signal_type == "deadline":
        decision.action = "submit"
        decision.task_type = "assignment_analysis"
        decision.task_title = f"Analyze assignment: {winner.title}"
        decision.task_summary = f"Assignment due in {winner.detail.get('days_until_due', '?')} day(s)."
        decision.input_json = {"assignment_id": winner.entity_id}
        decision.reason = f"Assignment due in {winner.detail.get('days_until_due')} day(s)."

    elif winner.signal_type == "forgetting_risk":
        decision.action = "submit"
        decision.task_type = "review_session"
        items = winner.detail.get("items", [])
        decision.task_title = f"Review {winner.detail.get('overdue_count', 0)} at-risk items"
        decision.task_summary = "Spaced repetition items are overdue."
        decision.input_json = {
            "course_id": str(winner.course_id) if winner.course_id else None,
            "session_kind": "due_review",
            "trigger_signal": "forgetting_risk",
            "duration_minutes": 10,
            "items": items,
            "content_mutation_hint": {
                "tool": "update_section_notes",
                "reason": "Student is forgetting this material — notes may need reinforcement",
            },
        }
        decision.reason = "Forgetting forecast shows material close to slipping below retention threshold."

    elif winner.signal_type == "prerequisite_gap":
        decision.action = "submit"
        decision.task_type = "prerequisite_review"
        concept = winner.detail.get("concept", "unknown")
        decision.task_title = f"Review prerequisite: {concept}"
        decision.task_summary = (
            f"Concept '{concept}' is a prerequisite gap "
            f"(mastery {winner.detail.get('mastery', 0):.0%}). "
            f"Strengthen this foundation before advancing."
        )
        decision.input_json = {
            "course_id": str(winner.course_id) if winner.course_id else None,
            "concept": concept,
            "concept_id": winner.detail.get("concept_id"),
            "trigger_signal": "prerequisite_gap",
            "content_mutation_hint": {
                "tool": "add_targeted_practice",
                "reason": f"Prerequisite gap detected for '{concept}' — generate foundational exercises",
            },
        }
        decision.reason = f"Prerequisite concept '{concept}' has low mastery — must strengthen before dependent topics."

    elif winner.signal_type == "weak_area":
        decision.action = "submit"
        decision.task_type = "wrong_answer_review"
        decision.task_title = f"Review {winner.detail.get('unmastered_count', 0)} weak areas"
        decision.task_summary = "Targeted exercises for unmastered wrong answers."
        decision.input_json = {
            "course_id": str(winner.course_id) if winner.course_id else None,
            "content_mutation_hint": {
                "tool": "add_targeted_practice",
                "reason": "High error rate on this topic — generate targeted practice",
            },
        }
        decision.reason = "Enough unmastered wrong answers to warrant a targeted review."

    elif winner.signal_type == "content_stale":
        decision.action = "submit"
        decision.task_type = "content_update"
        decision.task_title = f"Update content: {winner.title}"
        decision.task_summary = "Content has high error rates and hasn't been updated recently."
        decision.input_json = {
            "course_id": str(winner.course_id) if winner.course_id else None,
            "node_id": winner.entity_id,
            "content_mutation_hint": winner.detail.get("content_mutation_hint"),
        }
        decision.reason = f"Content stale with {winner.detail.get('wrong_answer_count', 0)} errors."

    elif winner.signal_type == "guided_session_ready":
        decision.action = "submit"
        decision.task_type = "guided_session"
        decision.task_title = "Guided study session available"
        decision.task_summary = "A personalized guided study session is ready."
        decision.input_json = {
            "course_id": str(winner.course_id) if winner.course_id else None,
            "trigger_signal": "guided_session_ready",
            "has_deadline": winner.detail.get("has_deadline", False),
        }
        decision.reason = "Student is active and has material to study. Guided session can help."

    elif winner.signal_type == "inactivity":
        decision.action = "submit"
        decision.task_type = "reentry_session"
        decision.task_title = "Welcome back — quick re-entry session"
        decision.task_summary = f"Inactive for {winner.detail.get('days_inactive', '?')} days. Preparing a low-friction restart."
        decision.input_json = {
            "trigger_signal": "inactivity",
            "days_inactive": winner.detail.get("days_inactive"),
        }
        decision.reason = f"User inactive for {winner.detail.get('days_inactive')} days."

    else:
        decision.action = "noop"
        decision.reason = f"Unknown signal type: {winner.signal_type}"

    return decision
