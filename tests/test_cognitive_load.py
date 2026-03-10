"""Tests for services/cognitive_load.py — cognitive load detection.

Covers:
- compute_cognitive_load(): signal aggregation, score clamping to [0,1]
- Individual signal isolation (fatigue, session length, errors, brevity, help-seeking)
- Edge cases: empty conversation, no quiz data, high-load consecutive tracking
- suggest_layout_simplification(): block hiding under high load
- adjust_review_order_for_load(): card reordering
- _build_guidance(): prompt fragment generation
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.cognitive_load import (
    _build_guidance,
    _consecutive_high,
    adjust_review_order_for_load,
    compute_cognitive_load,
    suggest_layout_simplification,
)


# ── Helpers ──

def _stub_config(**overrides):
    """Return a mock settings object with cognitive load defaults."""
    defaults = {
        "cognitive_load_weight_fatigue": 0.25,
        "cognitive_load_weight_session_length": 0.15,
        "cognitive_load_weight_errors": 0.20,
        "cognitive_load_weight_brevity": 0.10,
        "cognitive_load_weight_help_seeking": 0.15,
        "cognitive_load_weight_quiz_performance": 0.15,
        "cognitive_load_threshold_high": 0.6,
        "cognitive_load_threshold_medium": 0.3,
    }
    defaults.update(overrides)
    mock = MagicMock()
    for k, v in defaults.items():
        setattr(mock, k, v)
    return mock


def _mock_db_no_data():
    """DB mock that returns 0/empty for all queries."""
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar.return_value = 0

    empty_result = MagicMock()
    empty_result.scalar.return_value = None

    fetch_result = MagicMock()
    fetch_result.fetchall.return_value = []

    scalars_mock = MagicMock()
    scalars_mock.all.return_value = []

    def mock_execute(stmt):
        r = MagicMock()
        r.scalar.return_value = 0
        r.scalar_one_or_none.return_value = None
        r.scalars.return_value = scalars_mock
        r.fetchall.return_value = []
        return r

    db.execute = AsyncMock(side_effect=mock_execute)
    return db


def _mock_baseline(calibrated=False):
    """Return a mock baseline object."""
    baseline = MagicMock()
    baseline.is_calibrated = calibrated
    baseline.update = MagicMock()
    return baseline


# ── compute_cognitive_load: basic behavior ──


@pytest.mark.asyncio
async def test_score_in_zero_one_range():
    """Score should always be in [0.0, 1.0]."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        result = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=0.0, session_messages=0, user_message="",
        )

    assert 0.0 <= result["score"] <= 1.0
    assert result["level"] in ("low", "medium", "high")


@pytest.mark.asyncio
async def test_score_clamped_at_one():
    """Even with all signals maxed, score should not exceed 1.0."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={"frustration": 1.0, "confusion": 1.0}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        result = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=1.0, session_messages=100,
            user_message="help I'm confused and stuck",
        )

    assert result["score"] <= 1.0


# ── Individual signal isolation ──


@pytest.mark.asyncio
async def test_fatigue_signal_contributes():
    """High fatigue_score should raise the total load."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        low = await compute_cognitive_load(
            db, user_id, course_id, fatigue_score=0.0, session_messages=0, user_message="",
        )
        high = await compute_cognitive_load(
            db, user_id, course_id, fatigue_score=1.0, session_messages=0, user_message="",
        )

    assert high["score"] > low["score"]
    assert high["signals"]["fatigue"] == 1.0
    assert low["signals"]["fatigue"] == 0.0


@pytest.mark.asyncio
async def test_session_length_signal():
    """Long sessions (many messages) should raise session_length signal."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        result = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=0.0, session_messages=80, user_message="",
        )

    # 80 / 40 = 2.0, clamped to 1.0
    assert result["signals"]["session_length"] == 1.0


@pytest.mark.asyncio
async def test_help_seeking_signal():
    """Messages containing help keywords should trigger help_seeking signal."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        result = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=0.0, session_messages=0,
            user_message="I don't understand this, can you help me?",
        )

    assert result["signals"]["help_seeking"] == 1.0


@pytest.mark.asyncio
async def test_no_help_seeking_for_normal_message():
    """Normal messages should not trigger help_seeking."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        result = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=0.0, session_messages=0,
            user_message="The derivative of x squared is 2x",
        )

    assert result["signals"]["help_seeking"] == 0.0


@pytest.mark.asyncio
async def test_brevity_signal_only_after_session_context():
    """Brevity signal should only activate after 3+ session messages."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        # Short message but only 2 session messages -> no brevity signal
        result_early = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=0.0, session_messages=2, user_message="ok",
        )
        # Short message with 10 session messages -> brevity signal active
        result_late = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=0.0, session_messages=10, user_message="ok",
        )

    assert result_early["signals"]["message_brevity"] == 0.0
    assert result_late["signals"]["message_brevity"] > 0.0


# ── Edge cases ──


@pytest.mark.asyncio
async def test_empty_message():
    """Empty user_message should yield zero for message-dependent signals."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        result = await compute_cognitive_load(
            db, user_id, course_id,
            fatigue_score=0.0, session_messages=0, user_message="",
        )

    assert result["signals"]["help_seeking"] == 0.0
    assert result["signals"]["message_brevity"] == 0.0
    assert result["affect"] == {}


@pytest.mark.asyncio
async def test_level_classification():
    """Verify level thresholds: low < 0.3, medium < 0.6, high >= 0.6."""
    db = _mock_db_no_data()
    user_id = uuid.uuid4()
    course_id = uuid.uuid4()

    with patch("services.cognitive_load.settings", _stub_config()), \
         patch("services.cognitive_load_nlp.analyze_student_affect", new_callable=AsyncMock, return_value={}), \
         patch("services.cognitive_load_calibrator.get_or_create_baseline", return_value=_mock_baseline()), \
         patch("services.cognitive_load_calibrator.compute_relative_load", return_value={"calibrated": False, "adjustments": {}}):

        low = await compute_cognitive_load(
            db, user_id, course_id, fatigue_score=0.0, session_messages=0, user_message="",
        )
        high = await compute_cognitive_load(
            db, user_id, course_id, fatigue_score=1.0, session_messages=80,
            user_message="help I'm confused",
        )

    assert low["level"] == "low"
    assert high["level"] in ("medium", "high")


# ── _build_guidance ──


def test_guidance_low_is_empty():
    """Low cognitive load should produce empty guidance."""
    assert _build_guidance("low", 0.1, {}) == ""


def test_guidance_high_contains_adaptation_advice():
    """High cognitive load guidance should contain adaptation instructions."""
    guidance = _build_guidance("high", 0.75, {"unmastered_errors": 0.8, "session_length": 0.9})
    assert "ADAPT" in guidance
    assert "fundamentals" in guidance
    assert "concise" in guidance.lower()


def test_guidance_medium_contains_suggestion():
    """Medium load guidance should suggest simpler explanations."""
    guidance = _build_guidance("medium", 0.4, {})
    assert "simpler" in guidance.lower()


def test_guidance_consecutive_high_triggers_intervention():
    """3+ consecutive high-load messages should trigger intervention."""
    guidance = _build_guidance("high", 0.8, {}, consecutive=3)
    assert "break" in guidance.lower() or "struggling" in guidance.lower()


# ── suggest_layout_simplification ──


def test_no_simplification_below_threshold():
    """Scores below 0.7 should not trigger simplification."""
    result = suggest_layout_simplification(0.5, ["quiz", "notes", "forecast"])
    assert result["should_simplify"] is False
    assert result["blocks_to_hide"] == []


def test_simplification_hides_non_essential_blocks():
    """High load should hide non-essential blocks."""
    blocks = ["quiz", "notes", "agent_insight", "forecast", "knowledge_graph", "podcast"]
    result = suggest_layout_simplification(0.85, blocks)
    assert result["should_simplify"] is True
    assert len(result["blocks_to_hide"]) <= 3
    # agent_insight should be first to hide (lowest priority)
    assert "agent_insight" in result["blocks_to_hide"]


def test_simplification_skips_essential_blocks():
    """Essential blocks (quiz, notes) should never be hidden."""
    result = suggest_layout_simplification(0.9, ["quiz", "notes"])
    assert result["should_simplify"] is False


# ── adjust_review_order_for_load ──


def test_no_reorder_when_load_low():
    """Cards should not be reordered when load < 0.5."""
    cards = [
        {"id": "a", "fsrs": {"stability": 1.0}},
        {"id": "b", "fsrs": {"stability": 10.0}},
    ]
    result = adjust_review_order_for_load(0.3, cards)
    assert result[0]["id"] == "a"


def test_reorder_easiest_first_when_load_high():
    """Under high load, most stable (easiest) cards should come first."""
    cards = [
        {"id": "hard", "fsrs": {"stability": 1.0}},
        {"id": "easy", "fsrs": {"stability": 10.0}},
        {"id": "mid", "fsrs": {"stability": 5.0}},
    ]
    result = adjust_review_order_for_load(0.8, cards)
    assert result[0]["id"] == "easy"
    assert result[-1]["id"] == "hard"


def test_reorder_empty_cards():
    """Empty card list should be returned as-is."""
    result = adjust_review_order_for_load(0.9, [])
    assert result == []
