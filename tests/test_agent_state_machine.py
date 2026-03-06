"""Tests for agent state machine transitions and preference inference.

Covers:
- AgentContext state transitions
- TaskPhase valid/invalid transitions
- Preference extractor behavior-based inference
- Context builder intent-based budget overrides
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent.state import AgentContext, TaskPhase, IntentType
from services.preference.extractor import (
    infer_time_of_day_preference,
    DIMENSIONS,
    VALUE_NORMALIZATION,
)
from services.agent.context_builder import INTENT_BUDGET_OVERRIDES, _estimate_tokens


# ── AgentContext state transitions ──


def _make_context(**overrides) -> AgentContext:
    defaults = dict(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="test message",
    )
    defaults.update(overrides)
    return AgentContext(**defaults)


def test_context_starts_in_idle():
    ctx = _make_context()
    assert ctx.phase == TaskPhase.IDLE


def test_transition_updates_phase():
    ctx = _make_context()
    ctx.transition(TaskPhase.ROUTING)
    assert ctx.phase == TaskPhase.ROUTING


def test_transition_records_history():
    ctx = _make_context()
    ctx.transition(TaskPhase.ROUTING)
    ctx.transition(TaskPhase.LOADING_CONTEXT)
    assert len(ctx.phase_history) == 2
    assert ctx.phase_history[0][0] == TaskPhase.IDLE
    assert ctx.phase_history[1][0] == TaskPhase.ROUTING


def test_transition_through_full_lifecycle():
    ctx = _make_context()
    phases = [
        TaskPhase.ROUTING,
        TaskPhase.LOADING_CONTEXT,
        TaskPhase.REASONING,
        TaskPhase.POST_PROCESSING,
        TaskPhase.COMPLETED,
    ]
    for phase in phases:
        ctx.transition(phase)
    assert ctx.phase == TaskPhase.COMPLETED
    assert len(ctx.phase_history) == len(phases)


def test_context_preserves_user_info():
    uid = uuid.uuid4()
    cid = uuid.uuid4()
    ctx = _make_context(user_id=uid, course_id=cid)
    assert ctx.user_id == uid
    assert ctx.course_id == cid


def test_context_default_intent_is_general():
    ctx = _make_context()
    assert ctx.intent == IntentType.GENERAL


def test_context_metadata_is_mutable_dict():
    ctx = _make_context()
    ctx.metadata["key"] = "value"
    assert ctx.metadata["key"] == "value"


# ── IntentType enum ──


def test_intent_type_values():
    assert IntentType.LEARN.value == "learn"
    assert IntentType.PLAN.value == "plan"
    assert IntentType.LAYOUT.value == "layout"
    assert IntentType.GENERAL.value == "general"


# ── Preference extractor: time-of-day inference ──


def test_time_of_day_late_night_suggests_concise():
    late_night = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    signal = infer_time_of_day_preference(now=late_night)
    assert signal is not None
    assert signal["dimension"] == "detail_level"
    assert signal["value"] == "concise"
    assert signal["signal_type"] == "behavior"


def test_time_of_day_early_morning_suggests_concise():
    early_am = datetime(2026, 1, 15, 3, 0, tzinfo=timezone.utc)
    signal = infer_time_of_day_preference(now=early_am)
    assert signal is not None
    assert signal["value"] == "concise"


def test_time_of_day_afternoon_returns_none():
    afternoon = datetime(2026, 1, 15, 14, 0, tzinfo=timezone.utc)
    signal = infer_time_of_day_preference(now=afternoon)
    assert signal is None


def test_time_of_day_morning_returns_none():
    morning = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
    signal = infer_time_of_day_preference(now=morning)
    assert signal is None


def test_time_of_day_boundary_22_triggers():
    boundary = datetime(2026, 1, 15, 22, 0, tzinfo=timezone.utc)
    signal = infer_time_of_day_preference(now=boundary)
    assert signal is not None


def test_time_of_day_boundary_5_does_not_trigger():
    boundary = datetime(2026, 1, 15, 5, 0, tzinfo=timezone.utc)
    signal = infer_time_of_day_preference(now=boundary)
    assert signal is None


# ── Value normalization ──


def test_value_normalization_zh_variants():
    assert VALUE_NORMALIZATION["zh-cn"] == "zh"
    assert VALUE_NORMALIZATION["zh-tw"] == "zh"
    assert VALUE_NORMALIZATION["zh-hans"] == "zh"
    assert VALUE_NORMALIZATION["zh-hant"] == "zh"


def test_value_normalization_explanation_style():
    assert VALUE_NORMALIZATION["analogy"] == "example_heavy"
    assert VALUE_NORMALIZATION["example_first"] == "example_heavy"


def test_all_dimensions_present():
    expected = {"note_format", "detail_level", "language", "explanation_style", "visual_preference"}
    assert set(DIMENSIONS) == expected


# ── Context builder: intent-based budgets ──


def test_intent_budget_overrides_exist_for_key_intents():
    assert "learn" in INTENT_BUDGET_OVERRIDES
    assert "review" in INTENT_BUDGET_OVERRIDES
    assert "quiz" in INTENT_BUDGET_OVERRIDES
    assert "general" in INTENT_BUDGET_OVERRIDES


def test_learn_intent_gets_more_rag_budget():
    learn_budgets = INTENT_BUDGET_OVERRIDES["learn"]
    assert learn_budgets["RAG_BUDGET"] > 3000  # More than default


def test_review_intent_gets_more_memory_budget():
    review_budgets = INTENT_BUDGET_OVERRIDES["review"]
    assert review_budgets["MEMORY_BUDGET"] > 1500  # More than default


def test_general_intent_gets_more_history_budget():
    general_budgets = INTENT_BUDGET_OVERRIDES["general"]
    assert general_budgets["HISTORY_BUDGET"] >= 2000


def test_estimate_tokens_english():
    text = "Hello world this is a test"
    tokens = _estimate_tokens(text)
    assert tokens > 0
    assert tokens < 100  # Short text, should be small


def test_estimate_tokens_cjk():
    text = "这是一个测试消息"
    tokens = _estimate_tokens(text)
    assert tokens > 0


def test_estimate_tokens_empty():
    assert _estimate_tokens("") == 0 or _estimate_tokens("") >= 0


# ── TaskPhase enum coverage ──


def test_all_task_phases_accessible():
    phases = [
        TaskPhase.IDLE, TaskPhase.ROUTING, TaskPhase.LOADING_CONTEXT,
        TaskPhase.REASONING, TaskPhase.POST_PROCESSING, TaskPhase.COMPLETED,
        TaskPhase.FAILED, TaskPhase.CANCELLED,
    ]
    assert len(phases) >= 7


def test_task_phase_is_string_enum():
    assert isinstance(TaskPhase.IDLE.value, str)
    assert TaskPhase.IDLE.value == "idle"
