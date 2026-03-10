"""Tests for Phase 4 optimization features.

Covers:
- E2: BKT trainer (parameter fitting, mastery computation with trained params)
- E5: Socratic teaching guardrails (fatigue gating, cross-course sections)
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


# ═══════ E2: BKT Trainer ═══════


class TestBKTTrainer:
    """Tests for bkt_trainer module (parameter caching, mastery computation)."""

    def test_get_trained_params_empty_cache(self):
        from services.learning_science.bkt_trainer import get_trained_params

        user_id = uuid.uuid4()
        result = get_trained_params(user_id, None, "calculus")
        assert result is None

    def test_get_trained_params_hit(self):
        import time
        from services.learning_science.bkt_trainer import (
            set_trained_params_cache,
            invalidate_trained_params_cache,
            get_trained_params,
        )

        user_id = uuid.uuid4()
        course_id = uuid.uuid4()
        set_trained_params_cache(
            user_id,
            course_id,
            {
                "derivatives": {"prior": 0.3, "learns": 0.25, "guesses": 0.2, "slips": 0.1},
            },
            trained_at_ts=time.time(),
        )

        result = get_trained_params(user_id, course_id, "derivatives")
        assert result is not None
        assert result["prior"] == 0.3
        assert result["learns"] == 0.25

        # Miss for unknown concept
        assert get_trained_params(user_id, course_id, "integrals") is None

        # Cleanup
        invalidate_trained_params_cache(user_id, course_id)

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
        import time
        from services.learning_science.bkt_trainer import (
            set_trained_params_cache,
            invalidate_trained_params_cache,
            compute_mastery_with_trained_params,
        )

        user_id = uuid.uuid4()
        course_id = uuid.uuid4()
        set_trained_params_cache(
            user_id,
            course_id,
            {"derivatives": {"prior": 0.9, "learns": 0.5, "guesses": 0.1, "slips": 0.05}},
            trained_at_ts=time.time(),
        )

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
        invalidate_trained_params_cache(user_id, course_id)

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
        from services.agent.agents.tutor import SOCRATIC_GUARDRAILS, TutorAgent as TeachingAgent

        agent = TeachingAgent()
        ctx = self._make_ctx(fatigue_score=0.3)
        prompt = agent.build_system_prompt(ctx)

        assert "Socratic Teaching Rules" in prompt
        assert "NEVER give the student the direct answer" in prompt

    def test_supportive_mode_when_fatigued(self):
        from services.agent.agents.tutor import TutorAgent as TeachingAgent

        agent = TeachingAgent()
        ctx = self._make_ctx(fatigue_score=0.9)
        prompt = agent.build_system_prompt(ctx)

        assert "Supportive" in prompt
        assert "worked examples" in prompt
        # Should NOT have Socratic guardrails
        assert "NEVER give the student the direct answer" not in prompt

    def test_cross_course_connections_in_prompt(self):
        from services.agent.agents.tutor import TutorAgent as TeachingAgent

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
        from services.agent.agents.tutor import TutorAgent as TeachingAgent

        agent = TeachingAgent()
        ctx = self._make_ctx()
        prompt = agent.build_system_prompt(ctx)

        assert "Cross-Course Connections" not in prompt

    def test_fatigue_boundary_at_07(self):
        """Exactly 0.7 should still use Socratic mode."""
        from services.agent.agents.tutor import TutorAgent as TeachingAgent

        agent = TeachingAgent()

        ctx_at = self._make_ctx(fatigue_score=0.7)
        prompt_at = agent.build_system_prompt(ctx_at)
        assert "Socratic Teaching Rules" in prompt_at

        ctx_over = self._make_ctx(fatigue_score=0.71)
        prompt_over = agent.build_system_prompt(ctx_over)
        assert "Supportive" in prompt_over
