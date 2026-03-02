"""Tests for Phase 4 optimization features.

Covers:
- E1: Thompson Sampling bandit (strategy selection, reward observation, context vector)
- E2: BKT trainer (parameter fitting, mastery computation with trained params)
- E3: Score prediction (heuristic fallback, feature building)
- E4: GoalPursuit fault tolerance (consecutive failure counting, single failure skip)
- E5: Socratic teaching guardrails (fatigue gating, cross-course sections)
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# ═══════ E1: Thompson Sampling Bandit ═══════


class TestBanditContextVector:
    """Tests for build_context_vector()."""

    def test_default_context_shape(self):
        from services.experiment.bandit import build_context_vector

        ctx = build_context_vector()
        assert ctx.shape == (1, 6)

    def test_default_values_are_midpoint(self):
        from services.experiment.bandit import build_context_vector

        ctx = build_context_vector()
        # mastery=0.5, difficulty=0.5, familiarity=0.5, session=0/60=0, accuracy=0.5, help=0/10=0
        expected = [0.5, 0.5, 0.5, 0.0, 0.5, 0.0]
        np.testing.assert_array_almost_equal(ctx[0], expected)

    def test_clamps_out_of_range_values(self):
        from services.experiment.bandit import build_context_vector

        ctx = build_context_vector(
            mastery_score=1.5,
            difficulty_level=-0.3,
            recent_accuracy=2.0,
        )
        assert ctx[0][0] == 1.0  # clamped from 1.5
        assert ctx[0][1] == 0.0  # clamped from -0.3
        assert ctx[0][4] == 1.0  # clamped from 2.0

    def test_session_length_normalization(self):
        from services.experiment.bandit import build_context_vector

        ctx = build_context_vector(session_length_minutes=30.0)
        assert ctx[0][3] == pytest.approx(0.5)  # 30/60

        ctx120 = build_context_vector(session_length_minutes=120.0)
        assert ctx120[0][3] == 1.0  # clamped: 120/60 = 2.0 → 1.0

    def test_help_request_normalization(self):
        from services.experiment.bandit import build_context_vector

        ctx = build_context_vector(help_request_count=5)
        assert ctx[0][5] == pytest.approx(0.5)  # 5/10

        ctx_overflow = build_context_vector(help_request_count=20)
        assert ctx_overflow[0][5] == 1.0  # clamped: 20/10 = 2.0 → 1.0


class TestBanditStrategySelection:
    """Tests for select_strategy() — fallback path (no contextualbandits)."""

    def test_select_strategy_returns_valid_strategy(self):
        from services.experiment.bandit import (
            TEACHING_STRATEGIES,
            build_context_vector,
            select_strategy,
        )

        user_id = uuid.uuid4()
        ctx = build_context_vector()

        strategy, idx = select_strategy(user_id, ctx)

        assert strategy in TEACHING_STRATEGIES
        assert 0 <= idx < len(TEACHING_STRATEGIES)
        assert TEACHING_STRATEGIES[idx] == strategy

    def test_select_strategy_with_none_bandit_uses_random(self):
        """When _make_bandit returns None, fallback to random."""
        from services.experiment.bandit import (
            TEACHING_STRATEGIES,
            _bandit_cache,
            build_context_vector,
            select_strategy,
        )

        user_id = uuid.uuid4()
        _bandit_cache[str(user_id)] = None  # Force None (no contextualbandits)

        ctx = build_context_vector()
        strategy, idx = select_strategy(user_id, ctx)

        assert strategy in TEACHING_STRATEGIES
        assert 0 <= idx < len(TEACHING_STRATEGIES)

        # Cleanup
        del _bandit_cache[str(user_id)]


class TestBanditObserveReward:
    """Tests for observe_reward() — no-op when bandit is None."""

    def test_observe_reward_noop_when_bandit_none(self):
        from services.experiment.bandit import (
            _bandit_cache,
            build_context_vector,
            observe_reward,
        )

        user_id = uuid.uuid4()
        _bandit_cache[str(user_id)] = None

        ctx = build_context_vector()
        # Should not raise
        observe_reward(user_id, ctx, strategy_idx=0, reward=1.0)

        # Cleanup
        del _bandit_cache[str(user_id)]

    def test_observe_reward_calls_partial_fit(self):
        from services.experiment.bandit import (
            _bandit_cache,
            build_context_vector,
            observe_reward,
        )

        user_id = uuid.uuid4()
        mock_bandit = MagicMock()
        _bandit_cache[str(user_id)] = mock_bandit

        ctx = build_context_vector()
        observe_reward(user_id, ctx, strategy_idx=2, reward=1.0)

        mock_bandit.partial_fit.assert_called_once()
        args = mock_bandit.partial_fit.call_args
        np.testing.assert_array_equal(args[0][0], ctx)
        np.testing.assert_array_equal(args[0][1], np.array([2]))
        np.testing.assert_array_equal(args[0][2], np.array([1.0]))

        # Cleanup
        del _bandit_cache[str(user_id)]


@pytest.mark.asyncio
async def test_record_strategy_outcome_correct():
    from services.experiment.bandit import _bandit_cache, record_strategy_outcome

    user_id = uuid.uuid4()
    _bandit_cache[str(user_id)] = None  # Force None so observe_reward is a no-op

    context_vector = [[0.5, 0.5, 0.5, 0.0, 0.5, 0.0]]
    # Should not raise
    await record_strategy_outcome(user_id, strategy_idx=1, context_vector=context_vector, correct=True)

    del _bandit_cache[str(user_id)]


@pytest.mark.asyncio
async def test_select_strategy_for_context_returns_dict():
    from services.experiment.bandit import _bandit_cache, select_strategy_for_context

    user_id = uuid.uuid4()
    _bandit_cache[str(user_id)] = None

    db = MagicMock()

    # The function catches exceptions from the analytics import internally,
    # so we can pass a mock db and it will fall back to defaults
    result = await select_strategy_for_context(db, user_id, mastery_score=0.7)

    assert "strategy" in result
    assert "strategy_idx" in result
    assert "context_vector" in result
    assert isinstance(result["context_vector"], list)

    del _bandit_cache[str(user_id)]


# ═══════ E2: BKT Trainer ═══════


class TestBKTTrainer:
    """Tests for bkt_trainer module (parameter caching, mastery computation)."""

    def test_get_trained_params_empty_cache(self):
        from services.learning_science.bkt_trainer import get_trained_params

        user_id = uuid.uuid4()
        result = get_trained_params(user_id, None, "calculus")
        assert result is None

    def test_get_trained_params_hit(self):
        from services.learning_science.bkt_trainer import (
            _fitted_params_cache,
            get_trained_params,
        )

        user_id = uuid.uuid4()
        course_id = uuid.uuid4()
        cache_key = f"{user_id}:{course_id}"
        _fitted_params_cache[cache_key] = {
            "derivatives": {"prior": 0.3, "learns": 0.25, "guesses": 0.2, "slips": 0.1},
        }

        result = get_trained_params(user_id, course_id, "derivatives")
        assert result is not None
        assert result["prior"] == 0.3
        assert result["learns"] == 0.25

        # Miss for unknown concept
        assert get_trained_params(user_id, course_id, "integrals") is None

        # Cleanup
        del _fitted_params_cache[cache_key]

    def test_fit_with_pybkt_returns_empty_without_library(self):
        """When pyBKT is not installed, _fit_with_pybkt returns {}."""
        from services.learning_science.bkt_trainer import _fit_with_pybkt

        with patch.dict("sys.modules", {"pyBKT": None, "pyBKT.models": None}):
            result = _fit_with_pybkt([
                {"concept": "derivatives", "correct": True, "timestamp": datetime.now(timezone.utc)}
                for _ in range(20)
            ])
            # Will return {} because pyBKT ImportError is caught
            assert isinstance(result, dict)

    def test_fit_with_pybkt_skips_low_data_concepts(self):
        """Concepts with fewer than MIN_OBSERVATIONS_FOR_FIT are skipped."""
        from services.learning_science.bkt_trainer import MIN_OBSERVATIONS_FOR_FIT, _fit_with_pybkt

        # Provide just under the threshold
        data = [
            {"concept": "limits", "correct": i % 2 == 0, "timestamp": datetime.now(timezone.utc)}
            for i in range(MIN_OBSERVATIONS_FOR_FIT - 1)
        ]

        # Even if pyBKT is importable, low-data concepts are filtered before fitting
        result = _fit_with_pybkt(data)
        # Should not contain "limits"
        assert "limits" not in result

    def test_compute_mastery_with_trained_params_uses_cache(self):
        """When trained params are cached, they're used instead of defaults."""
        from services.learning_science.bkt_trainer import (
            _fitted_params_cache,
            compute_mastery_with_trained_params,
        )

        user_id = uuid.uuid4()
        course_id = uuid.uuid4()
        cache_key = f"{user_id}:{course_id}"
        _fitted_params_cache[cache_key] = {
            "derivatives": {"prior": 0.9, "learns": 0.5, "guesses": 0.1, "slips": 0.05},
        }

        # Mastery with trained params (high prior, high learns) should be high
        mastery = compute_mastery_with_trained_params(
            results=[True, True, True],
            concept="derivatives",
            user_id=user_id,
            course_id=course_id,
        )
        assert 0.0 <= mastery <= 1.0
        assert mastery > 0.5  # High prior + correct answers → high mastery

        # Cleanup
        del _fitted_params_cache[cache_key]

    def test_compute_mastery_fallback_to_heuristic(self):
        """When no trained params, falls back to heuristic."""
        from services.learning_science.bkt_trainer import compute_mastery_with_trained_params

        user_id = uuid.uuid4()
        mastery = compute_mastery_with_trained_params(
            results=[True, False, True, True],
            concept="unknown_topic",
            user_id=user_id,
            course_id=None,
        )
        assert 0.0 <= mastery <= 1.0


# ═══════ E3: Score Prediction ═══════


class TestScorePrediction:
    """Tests for score_predictor module."""

    def test_build_features_from_state(self):
        from services.prediction.score_predictor import _build_features_from_state

        state = {
            "avg_mastery": 0.8,
            "study_hours_last_7d": 10.0,
            "quiz_accuracy": 0.75,
            "days_until_exam": 14,
            "review_consistency": 0.6,
            "num_topics_mastered": 5,
            "total_topics": 10,
            "flashcard_retention": 0.7,
        }
        features = _build_features_from_state(state)

        assert len(features) == 7
        assert features[0] == 0.8      # avg_mastery
        assert features[1] == 0.5      # 10/20
        assert features[2] == 0.75     # quiz_accuracy
        assert features[3] == pytest.approx(14 / 60.0)  # days/60
        assert features[4] == 0.6      # review_consistency
        assert features[5] == 0.5      # 5/10
        assert features[6] == 0.7      # flashcard_retention

    def test_build_features_handles_missing_keys(self):
        from services.prediction.score_predictor import _build_features_from_state

        features = _build_features_from_state({})
        assert len(features) == 7
        assert features[0] == 0.5  # default mastery
        assert features[1] == 0.0  # 0/20

    def test_heuristic_predict_returns_required_fields(self):
        from services.prediction.score_predictor import _heuristic_predict

        state = {
            "avg_mastery": 0.8,
            "quiz_accuracy": 0.9,
            "review_consistency": 0.7,
            "flashcard_retention": 0.85,
            "days_until_exam": 14,
            "study_hours_last_7d": 10.0,
        }
        result = _heuristic_predict(state)

        assert "predicted_score" in result
        assert "confidence" in result
        assert "with_extra_30min_daily" in result
        assert "improvement_potential" in result
        assert "model" in result
        assert result["model"] == "heuristic"
        assert result["confidence"] == "low"

    def test_heuristic_predict_score_range(self):
        from services.prediction.score_predictor import _heuristic_predict

        # High performer
        result_high = _heuristic_predict({
            "avg_mastery": 1.0,
            "quiz_accuracy": 1.0,
            "review_consistency": 1.0,
            "flashcard_retention": 1.0,
            "days_until_exam": 7,
            "study_hours_last_7d": 20.0,
        })
        assert 0 <= result_high["predicted_score"] <= 100

        # Low performer
        result_low = _heuristic_predict({
            "avg_mastery": 0.1,
            "quiz_accuracy": 0.1,
            "review_consistency": 0.1,
            "flashcard_retention": 0.1,
            "days_until_exam": 1,
            "study_hours_last_7d": 0.5,
        })
        assert 0 <= result_low["predicted_score"] <= 100
        assert result_high["predicted_score"] > result_low["predicted_score"]

    def test_heuristic_predict_improvement_potential_non_negative(self):
        from services.prediction.score_predictor import _heuristic_predict

        result = _heuristic_predict({
            "avg_mastery": 0.5,
            "quiz_accuracy": 0.5,
            "review_consistency": 0.5,
            "flashcard_retention": 0.5,
            "days_until_exam": 14,
            "study_hours_last_7d": 5.0,
        })
        assert result["improvement_potential"] >= 0
        assert result["with_extra_30min_daily"] >= result["predicted_score"]


# ═══════ E4: GoalPursuit Fault Tolerance ═══════

# node_replan lives in services.workflow.graph which has a top-level
# ``from langgraph.graph import StateGraph, END`` that fails when
# langgraph is not installed.  Since the replan logic itself is pure
# Python, we mock the langgraph import so we can test node_replan in
# isolation.

_langgraph_mocked = False


def _ensure_langgraph_mock():
    """Install a minimal langgraph stub if the real package is absent."""
    global _langgraph_mocked
    if _langgraph_mocked:
        return
    try:
        import langgraph  # noqa: F401
    except ImportError:
        import sys
        import types

        # Minimal stubs so ``from langgraph.graph import StateGraph, END`` works
        lg = types.ModuleType("langgraph")
        lg_graph = types.ModuleType("langgraph.graph")

        class _FakeStateGraph:
            def __init__(self, *a, **kw):
                pass
            def add_node(self, *a, **kw): pass
            def add_edge(self, *a, **kw): pass
            def add_conditional_edges(self, *a, **kw): pass
            def set_entry_point(self, *a, **kw): pass
            def compile(self, **kw): return self

        lg_graph.StateGraph = _FakeStateGraph
        lg_graph.END = "__end__"
        lg.graph = lg_graph
        sys.modules["langgraph"] = lg
        sys.modules["langgraph.graph"] = lg_graph

    _langgraph_mocked = True


class TestGoalPursuitReplan:
    """Tests for node_replan() fault tolerance logic."""

    @staticmethod
    def _get_node_replan():
        _ensure_langgraph_mock()
        from services.workflow.graph import node_replan
        return node_replan

    @pytest.mark.asyncio
    async def test_replan_continues_after_single_failure(self):
        """A single step failure should NOT abort — continues to next step."""
        node_replan = self._get_node_replan()

        state = {
            "plan": [
                {"title": "Step 1", "tool": "generate_quiz"},
                {"title": "Step 2", "tool": "create_flashcard"},
                {"title": "Step 3", "tool": "review_material"},
            ],
            "current_step": 1,
            "max_steps": 5,
            "observations": [
                {"step": 0, "result": "Failed: connection error"},
            ],
            "done": False,
            "user_id": uuid.uuid4(),
            "course_id": None,
            "goal_id": uuid.uuid4(),
            "goal_title": "Test",
            "goal_objective": "Test",
        }
        config = {"configurable": {"db": MagicMock()}}

        result = await node_replan(state, config)
        assert result["done"] is False  # Should continue

    @pytest.mark.asyncio
    async def test_replan_stops_after_two_consecutive_failures(self):
        """Two consecutive failures should abort."""
        node_replan = self._get_node_replan()

        state = {
            "plan": [
                {"title": "Step 1", "tool": "generate_quiz"},
                {"title": "Step 2", "tool": "create_flashcard"},
                {"title": "Step 3", "tool": "review_material"},
            ],
            "current_step": 2,
            "max_steps": 5,
            "observations": [
                {"step": 0, "result": "Failed: connection error"},
                {"step": 1, "result": "Failed: timeout"},
            ],
            "done": False,
            "user_id": uuid.uuid4(),
            "course_id": None,
            "goal_id": uuid.uuid4(),
            "goal_title": "Test",
            "goal_objective": "Test",
        }
        config = {"configurable": {"db": MagicMock()}}

        result = await node_replan(state, config)
        assert result["done"] is True  # Should abort

    @pytest.mark.asyncio
    async def test_replan_continues_after_failure_then_success(self):
        """A failure followed by a success resets the consecutive counter."""
        node_replan = self._get_node_replan()

        state = {
            "plan": [
                {"title": "Step 1", "tool": "generate_quiz"},
                {"title": "Step 2", "tool": "create_flashcard"},
                {"title": "Step 3", "tool": "review_material"},
            ],
            "current_step": 2,
            "max_steps": 5,
            "observations": [
                {"step": 0, "result": "Failed: connection error"},
                {"step": 1, "result": "Queued task: abc123"},
            ],
            "done": False,
            "user_id": uuid.uuid4(),
            "course_id": None,
            "goal_id": uuid.uuid4(),
            "goal_title": "Test",
            "goal_objective": "Test",
        }
        config = {"configurable": {"db": MagicMock()}}

        result = await node_replan(state, config)
        assert result["done"] is False  # Should continue — only 0 consecutive failures

    @pytest.mark.asyncio
    async def test_replan_stops_when_all_steps_complete(self):
        """When current_step >= len(plan), should finish."""
        node_replan = self._get_node_replan()

        state = {
            "plan": [{"title": "Step 1", "tool": "generate_quiz"}],
            "current_step": 1,
            "max_steps": 5,
            "observations": [
                {"step": 0, "result": "Queued task: abc123"},
            ],
            "done": False,
            "user_id": uuid.uuid4(),
            "course_id": None,
            "goal_id": uuid.uuid4(),
            "goal_title": "Test",
            "goal_objective": "Test",
        }
        config = {"configurable": {"db": MagicMock()}}

        result = await node_replan(state, config)
        assert result["done"] is True

    @pytest.mark.asyncio
    async def test_replan_stops_at_max_steps(self):
        """Even with incomplete plan, should stop at max_steps."""
        node_replan = self._get_node_replan()

        state = {
            "plan": [
                {"title": f"Step {i}", "tool": "review_material"}
                for i in range(10)
            ],
            "current_step": 3,
            "max_steps": 3,
            "observations": [],
            "done": False,
            "user_id": uuid.uuid4(),
            "course_id": None,
            "goal_id": uuid.uuid4(),
            "goal_title": "Test",
            "goal_objective": "Test",
        }
        config = {"configurable": {"db": MagicMock()}}

        result = await node_replan(state, config)
        assert result["done"] is True


# ═══════ E5: Socratic Teaching Guardrails ═══════


class TestTeachingAgentPrompt:
    """Tests for TeachingAgent.build_system_prompt() with guardrails."""

    def _make_ctx(self, fatigue_score=0.0, cross_patterns=None):
        from services.agent.state import AgentContext

        ctx = AgentContext(
            user_id=uuid.uuid4(),
            course_id=uuid.uuid4(),
            user_message="What is a derivative?",
        )
        ctx.metadata["fatigue_score"] = fatigue_score
        if cross_patterns:
            ctx.metadata["cross_course_patterns"] = cross_patterns
        return ctx

    def test_socratic_guardrails_injected_when_not_fatigued(self):
        from services.agent.teaching import SOCRATIC_GUARDRAILS, TeachingAgent

        agent = TeachingAgent()
        ctx = self._make_ctx(fatigue_score=0.3)
        prompt = agent.build_system_prompt(ctx)

        assert "Socratic Teaching Rules" in prompt
        assert "NEVER give the student the direct answer" in prompt

    def test_supportive_mode_when_fatigued(self):
        from services.agent.teaching import TeachingAgent

        agent = TeachingAgent()
        ctx = self._make_ctx(fatigue_score=0.9)
        prompt = agent.build_system_prompt(ctx)

        assert "Supportive" in prompt
        assert "worked examples" in prompt
        # Should NOT have Socratic guardrails
        assert "NEVER give the student the direct answer" not in prompt

    def test_cross_course_connections_in_prompt(self):
        from services.agent.teaching import TeachingAgent

        patterns = [
            {
                "topic": "Probability",
                "courses": [
                    {"course_name": "Statistics 101", "mastery": "0.8"},
                    {"course_name": "Machine Learning", "mastery": "0.3"},
                ],
            },
        ]

        agent = TeachingAgent()
        ctx = self._make_ctx(cross_patterns=patterns)
        prompt = agent.build_system_prompt(ctx)

        assert "Cross-Course Connections" in prompt
        assert "Probability" in prompt
        assert "Statistics 101" in prompt
        assert "Machine Learning" in prompt

    def test_no_cross_course_when_empty(self):
        from services.agent.teaching import TeachingAgent

        agent = TeachingAgent()
        ctx = self._make_ctx()
        prompt = agent.build_system_prompt(ctx)

        assert "Cross-Course Connections" not in prompt

    def test_fatigue_boundary_at_07(self):
        """Exactly 0.7 should still use Socratic mode."""
        from services.agent.teaching import TeachingAgent

        agent = TeachingAgent()

        ctx_at = self._make_ctx(fatigue_score=0.7)
        prompt_at = agent.build_system_prompt(ctx_at)
        assert "Socratic Teaching Rules" in prompt_at

        ctx_over = self._make_ctx(fatigue_score=0.71)
        prompt_over = agent.build_system_prompt(ctx_over)
        assert "Supportive" in prompt_over
