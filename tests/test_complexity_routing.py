"""Tests for multi-level model routing via complexity scoring."""

import pytest

from services.llm.complexity import (
    ModelTier,
    AGENT_MIN_TIERS,
    score_complexity,
    resolve_tier,
    FAST_THRESHOLD,
    FRONTIER_THRESHOLD,
    _score_message_length,
    _score_intent,
    _score_scene,
    _score_conversation_depth,
    _score_complexity_markers,
)


# ── Message Length Scoring ──


def test_short_greeting_low_score():
    assert _score_message_length("hi") == 0


def test_medium_message():
    msg = "Can you explain binary search to me?"
    score = _score_message_length(msg)
    assert 20 <= score <= 80


def test_long_message_high_score():
    msg = "x" * 600
    assert _score_message_length(msg) == 150


# ── Intent Scoring ──


def test_preference_intent_low():
    assert _score_intent("preference") == 30


def test_learn_intent_moderate():
    assert _score_intent("learn") == 150


def test_plan_intent_high():
    assert _score_intent("plan") == 250


def test_code_intent_high():
    assert _score_intent("code") == 250


def test_unknown_intent_default():
    assert _score_intent("unknown") == 100


# ── Scene Scoring ──


def test_study_session_no_bonus():
    assert _score_scene("study_session") == 0


def test_exam_prep_high_bonus():
    assert _score_scene("exam_prep") == 80


# ── Conversation Depth ──


def test_short_conversation_no_score():
    assert _score_conversation_depth(2) == 0


def test_moderate_conversation():
    assert _score_conversation_depth(8) == 40  # 4 extra * 10


def test_long_conversation_capped():
    assert _score_conversation_depth(20) == 80  # capped at 8 * 10


# ── Complexity Markers ──


def test_no_markers():
    assert _score_complexity_markers("hello how are you") == 0


def test_step_by_step_marker():
    score = _score_complexity_markers("explain step by step")
    assert score >= 40


def test_prove_marker():
    score = _score_complexity_markers("prove that this theorem holds")
    assert score >= 50


def test_cjk_marker():
    score = _score_complexity_markers("请证明这个定理")
    assert score >= 50


def test_multiple_markers_capped():
    msg = "compare and contrast, step by step, prove, derive, and analyze"
    score = _score_complexity_markers(msg)
    assert score == 100  # capped


# ── Full Complexity Score ──


def test_greeting_is_low():
    score = score_complexity("hi", intent="general", scene="study_session")
    assert score < FAST_THRESHOLD


def test_learning_question_is_moderate():
    score = score_complexity(
        "Can you explain how binary search works?",
        intent="learn",
        scene="study_session",
    )
    assert FAST_THRESHOLD <= score < FRONTIER_THRESHOLD


def test_complex_planning_is_high():
    score = score_complexity(
        "Design a step-by-step study plan for my final exam covering chapters 1-12, "
        "comparing different strategies and analyzing my weak areas",
        intent="plan",
        scene="exam_prep",
        history_length=15,
        has_rag_context=True,
    )
    assert score >= FRONTIER_THRESHOLD


# ── Tier Resolution ──


def test_greeting_preference_agent_is_fast():
    tier = resolve_tier(
        agent_name="preference",
        message="hi",
        intent="preference",
        scene="study_session",
    )
    assert tier == ModelTier.FAST


def test_teaching_simple_is_standard():
    """Teaching agent has min tier = standard, even for simple messages."""
    tier = resolve_tier(
        agent_name="teaching",
        message="hello",
        intent="general",
        scene="study_session",
    )
    assert tier == ModelTier.STANDARD


def test_teaching_complex_stays_standard():
    tier = resolve_tier(
        agent_name="teaching",
        message="explain binary search to me",
        intent="learn",
        scene="study_session",
    )
    assert tier == ModelTier.STANDARD


def test_planning_always_at_least_frontier():
    """Planning agent has min tier = frontier."""
    tier = resolve_tier(
        agent_name="planning",
        message="hello",
        intent="general",
        scene="study_session",
    )
    assert tier == ModelTier.FRONTIER


def test_code_execution_always_at_least_frontier():
    tier = resolve_tier(
        agent_name="code_execution",
        message="run this",
        intent="code",
        scene="study_session",
    )
    assert tier == ModelTier.FRONTIER


def test_complex_request_upgrades_teaching_to_frontier():
    """A very complex request should upgrade teaching to frontier."""
    tier = resolve_tier(
        agent_name="teaching",
        message="Compare and contrast iterative vs recursive approaches step by step, "
        "prove the time complexity, and analyze the tradeoffs for each approach",
        intent="learn",
        scene="exam_prep",
        history_length=20,
        has_rag_context=True,
    )
    assert tier == ModelTier.FRONTIER


def test_unknown_agent_defaults_to_standard():
    """Unknown agents default to standard tier."""
    tier = resolve_tier(
        agent_name="unknown_plugin_agent",
        message="hello",
        intent="general",
    )
    assert tier == ModelTier.STANDARD


def test_motivation_simple_is_fast():
    tier = resolve_tier(
        agent_name="motivation",
        message="I'm feeling tired",
        intent="general",
        scene="study_session",
    )
    assert tier == ModelTier.FAST


def test_scene_agent_is_fast():
    tier = resolve_tier(
        agent_name="scene",
        message="switch to exam prep",
        intent="scene_switch",
    )
    assert tier == ModelTier.FAST


# ── Agent Min Tiers Coverage ──


def test_all_agents_have_min_tiers():
    """All 10 known agents should have min tier declarations."""
    expected_agents = {
        "teaching", "exercise", "planning", "review",
        "preference", "scene", "code_execution",
        "curriculum", "assessment", "motivation",
    }
    assert set(AGENT_MIN_TIERS.keys()) == expected_agents
