"""Tests for deterministic agenda ranking and decision logic.

Covers:
- Signal priority ordering
- Decision action mapping per signal type
- Dedup key generation
- Edge cases: empty signals, unknown types
"""

import uuid
from datetime import datetime, timezone

import pytest

from services.agent.agenda_ranking import AgendaDecision, rank_signals, _sort_key
from services.agent.agenda_signals import AgendaSignal


def _make_signal(signal_type: str, urgency: float = 50.0, **kwargs) -> AgendaSignal:
    defaults = dict(
        signal_type=signal_type,
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        entity_id=str(uuid.uuid4()),
        title=f"Test {signal_type}",
        urgency=urgency,
        detail={},
    )
    defaults.update(kwargs)
    return AgendaSignal(**defaults)


# ── Ranking order ──


def test_empty_signals_returns_noop():
    decision = rank_signals([])
    assert decision.action == "noop"
    assert decision.signal is None


def test_single_signal_wins():
    signal = _make_signal("active_goal", urgency=60, detail={"has_next_action": False, "objective": "test"})
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.signal is signal


def test_failed_task_beats_active_goal():
    """Failed task recovery has highest precedence."""
    failed = _make_signal("failed_task", urgency=80, detail={"status": "failed", "task_type": "multi_step"})
    goal = _make_signal("active_goal", urgency=90, detail={"has_next_action": True, "objective": "test", "next_action": "do it"})
    decision = rank_signals([goal, failed])
    assert decision.signal.signal_type == "failed_task"


def test_deadline_beats_forgetting_risk():
    deadline = _make_signal("deadline", urgency=85, detail={"days_until_due": 3})
    forgetting = _make_signal("forgetting_risk", urgency=80, detail={"overdue_count": 5, "items": []})
    decision = rank_signals([forgetting, deadline])
    assert decision.signal.signal_type == "deadline"


def test_forgetting_risk_beats_weak_area():
    forgetting = _make_signal("forgetting_risk", urgency=75, detail={"overdue_count": 3, "items": []})
    weak = _make_signal("weak_area", urgency=70, detail={"unmastered_count": 5})
    decision = rank_signals([weak, forgetting])
    assert decision.signal.signal_type == "forgetting_risk"


def test_weak_area_beats_inactivity():
    weak = _make_signal("weak_area", urgency=60, detail={"unmastered_count": 4})
    inactive = _make_signal("inactivity", urgency=55, detail={"days_inactive": 5})
    decision = rank_signals([inactive, weak])
    assert decision.signal.signal_type == "weak_area"


def test_active_goal_beats_inactivity():
    goal = _make_signal("active_goal", urgency=60, detail={"has_next_action": False, "objective": "learn"})
    inactive = _make_signal("inactivity", urgency=55, detail={"days_inactive": 4})
    decision = rank_signals([inactive, goal])
    assert decision.signal.signal_type == "active_goal"


# ── Decision action mapping ──


def test_failed_task_cancelled_becomes_resume():
    signal = _make_signal("failed_task", detail={"status": "cancelled", "task_type": "multi_step"})
    decision = rank_signals([signal])
    assert decision.action == "resume"
    assert decision.existing_task_id is not None


def test_failed_task_failed_becomes_retry():
    signal = _make_signal("failed_task", detail={"status": "failed", "task_type": "multi_step"})
    decision = rank_signals([signal])
    assert decision.action == "retry"


def test_active_goal_with_next_action():
    signal = _make_signal(
        "active_goal", urgency=90,
        detail={"has_next_action": True, "next_action": "Read chapter 3", "objective": "Learn math"},
    )
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.task_type == "multi_step"
    assert "chapter 3" in (decision.plan_prompt or "").lower() or "chapter 3" in (decision.task_summary or "").lower()


def test_active_goal_near_deadline():
    signal = _make_signal(
        "active_goal", urgency=85,
        detail={"has_next_action": False, "days_until_target": 5, "objective": "Pass exam"},
    )
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.task_type == "exam_prep"


def test_active_goal_generic():
    signal = _make_signal(
        "active_goal", urgency=60,
        detail={"has_next_action": False, "days_until_target": None, "objective": "Learn"},
    )
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.task_type == "multi_step"


def test_deadline_creates_assignment_analysis():
    signal = _make_signal("deadline", detail={"days_until_due": 2})
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.task_type == "assignment_analysis"


def test_forgetting_risk_creates_review_session():
    signal = _make_signal("forgetting_risk", detail={"overdue_count": 7, "items": [{"title": "Calculus"}]})
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.task_type == "review_session"
    assert decision.input_json.get("session_kind") == "due_review"


def test_weak_area_creates_wrong_answer_review():
    signal = _make_signal("weak_area", detail={"unmastered_count": 8})
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.task_type == "wrong_answer_review"


def test_inactivity_creates_reentry_session():
    signal = _make_signal("inactivity", detail={"days_inactive": 5})
    decision = rank_signals([signal])
    assert decision.action == "submit"
    assert decision.task_type == "reentry_session"


# ── Dedup key ──


def test_dedup_key_includes_date_bucket():
    signal = _make_signal("forgetting_risk", detail={"overdue_count": 1, "items": []})
    decision = rank_signals([signal])
    assert decision.dedup_key is not None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert today in decision.dedup_key


def test_dedup_key_includes_signal_type():
    signal = _make_signal("weak_area", detail={"unmastered_count": 5})
    decision = rank_signals([signal])
    assert "weak_area" in decision.dedup_key


# ── Sort key ──


def test_sort_key_orders_by_precedence_then_urgency():
    failed = _make_signal("failed_task", urgency=80)
    goal_high = _make_signal("active_goal", urgency=90)
    goal_low = _make_signal("active_goal", urgency=60)
    inactive = _make_signal("inactivity", urgency=50)

    signals = [inactive, goal_low, goal_high, failed]
    sorted_signals = sorted(signals, key=_sort_key)

    assert sorted_signals[0].signal_type == "failed_task"
    assert sorted_signals[1].signal_type == "active_goal"
    assert sorted_signals[1].urgency == 90
    assert sorted_signals[2].signal_type == "active_goal"
    assert sorted_signals[2].urgency == 60
    assert sorted_signals[3].signal_type == "inactivity"


# ── Decision serialization ──


def test_decision_to_dict():
    signal = _make_signal("active_goal", detail={"has_next_action": False, "objective": "test"})
    decision = rank_signals([signal])
    d = decision.to_dict()
    assert "action" in d
    assert "signal_type" in d
    assert d["signal_type"] == "active_goal"
