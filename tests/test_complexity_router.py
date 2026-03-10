"""Tests for LLM complexity scoring and model tier routing."""

from services.llm.complexity import (
    ModelTier,
    score_complexity,
    resolve_tier,
    _score_message_length,
    _score_intent,
    _score_scene,
    _score_conversation_depth,
    _score_complexity_markers,
    FAST_THRESHOLD,
    FRONTIER_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Sub-scoring functions
# ---------------------------------------------------------------------------

class TestScoreMessageLength:
    def test_very_short(self):
        assert _score_message_length("hi") == 0

    def test_short(self):
        assert _score_message_length("What is calculus?") == 0  # 17 chars

    def test_medium_short(self):
        assert _score_message_length("x" * 30) == 30

    def test_medium(self):
        assert _score_message_length("x" * 100) == 70

    def test_long(self):
        assert _score_message_length("x" * 300) == 100

    def test_very_long(self):
        assert _score_message_length("x" * 600) == 150


class TestScoreIntent:
    def test_known_intents(self):
        assert _score_intent("preference") == 30
        assert _score_intent("plan") == 250
        assert _score_intent("learn") == 150

    def test_unknown_intent(self):
        assert _score_intent("something_else") == 100


class TestScoreScene:
    def test_known_scenes(self):
        assert _score_scene("exam_prep") == 80
        assert _score_scene("study_session") == 0

    def test_unknown_scene(self):
        assert _score_scene("unknown") == 0


class TestScoreConversationDepth:
    def test_short_conversation(self):
        assert _score_conversation_depth(2) == 0

    def test_at_threshold(self):
        assert _score_conversation_depth(4) == 0

    def test_moderate(self):
        assert _score_conversation_depth(8) == 40

    def test_capped(self):
        assert _score_conversation_depth(100) == 80


class TestScoreComplexityMarkers:
    def test_no_markers(self):
        assert _score_complexity_markers("hello world") == 0

    def test_prove(self):
        score = _score_complexity_markers("Prove that the sum converges")
        assert score >= 50

    def test_step_by_step(self):
        score = _score_complexity_markers("Explain step by step")
        assert score >= 40

    def test_cjk_markers(self):
        score = _score_complexity_markers("请证明这个定理")
        assert score >= 50

    def test_capped_at_100(self):
        msg = "compare contrast prove derive step-by-step analyze design optimize debug"
        assert _score_complexity_markers(msg) == 100


# ---------------------------------------------------------------------------
# Composite scoring
# ---------------------------------------------------------------------------

class TestScoreComplexity:
    def test_simple_greeting(self):
        score = score_complexity("hi", intent="general")
        assert score < FAST_THRESHOLD

    def test_complex_request(self):
        score = score_complexity(
            "Prove step-by-step that the derivative of sin(x) is cos(x)",
            intent="plan",
            scene="exam_prep",
            history_length=15,
            has_rag_context=True,
        )
        assert score >= FRONTIER_THRESHOLD

    def test_rag_bonus(self):
        base = score_complexity("explain this concept", intent="learn")
        with_rag = score_complexity("explain this concept", intent="learn", has_rag_context=True)
        assert with_rag == base + 50


# ---------------------------------------------------------------------------
# Tier resolution
# ---------------------------------------------------------------------------

class TestResolveTier:
    def test_fast_agent_simple_message(self):
        tier = resolve_tier("preference", "change my theme")
        assert tier == ModelTier.FAST

    def test_teaching_agent_minimum_standard(self):
        tier = resolve_tier("teaching", "hi")
        assert tier == ModelTier.STANDARD

    def test_planning_agent_minimum_frontier(self):
        tier = resolve_tier("planning", "hi")
        assert tier == ModelTier.FRONTIER

    def test_high_complexity_overrides_agent_min(self):
        tier = resolve_tier(
            "preference",
            "Compare and contrast and prove step-by-step " * 10,
            intent="plan",
            scene="exam_prep",
            history_length=15,
            has_rag_context=True,
        )
        assert tier == ModelTier.FRONTIER

    def test_unknown_agent_defaults_standard(self):
        tier = resolve_tier("unknown_agent", "hi")
        assert tier == ModelTier.STANDARD
