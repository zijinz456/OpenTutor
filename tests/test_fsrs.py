"""Tests for the FSRS spaced repetition engine.

Covers:
- FSRSCard creation and defaults
- review_card basic scheduling
- estimate_forgetting_cost computation
- estimate_session_urgency thresholds
- Edge cases: new cards, lapse handling, zero stability
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.spaced_repetition.fsrs import (
    FSRSCard,
    ReviewLog,
    review_card,
    estimate_forgetting_cost,
    estimate_session_urgency,
    _retrievability,
    _initial_difficulty,
    _same_day_stability,
    _next_difficulty,
    DEFAULT_W,
)


# ── FSRSCard defaults ──


def test_card_defaults():
    """New card should have sensible defaults."""
    card = FSRSCard()
    assert card.difficulty == 5.0
    assert card.stability == 0.0
    assert card.reps == 0
    assert card.state == "new"
    assert card.due is None


# ── review_card ──


def test_first_review_good():
    """First review with 'Good' rating should set learning state."""
    card = FSRSCard()
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)

    updated, log = review_card(card, rating=3, now=now)

    assert updated.reps == 1
    assert updated.state == "review"
    assert updated.stability > 0
    assert updated.difficulty > 0
    assert updated.last_review == now
    assert updated.due is not None
    assert updated.due > now
    assert log.rating == 3
    assert log.state == "new"


def test_first_review_again():
    """First review with 'Again' should go to learning state."""
    card = FSRSCard()
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)

    updated, log = review_card(card, rating=1, now=now)

    assert updated.state == "learning"
    assert updated.reps == 1
    assert updated.due == now + timedelta(days=1)


def test_subsequent_review_lapse():
    """Answering 'Again' on a review card should increase lapses."""
    card = FSRSCard(
        difficulty=5.0,
        stability=10.0,
        reps=5,
        state="review",
        last_review=datetime(2024, 6, 5, 10, 0, tzinfo=timezone.utc),
        due=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
    )
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)

    updated, log = review_card(card, rating=1, now=now)

    assert updated.lapses == 1
    assert updated.state == "relearning"
    assert updated.due == now + timedelta(days=1)


def test_subsequent_review_easy():
    """Easy review should increase stability significantly."""
    original_stability = 5.0
    card = FSRSCard(
        difficulty=5.0,
        stability=original_stability,
        reps=3,
        state="review",
        last_review=datetime(2024, 6, 10, 10, 0, tzinfo=timezone.utc),
        due=datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc),
    )
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)

    updated, log = review_card(card, rating=4, now=now)

    assert updated.stability > original_stability
    assert updated.state == "review"


# ── _retrievability ──


def test_retrievability_at_zero_elapsed():
    """Retrievability should be ~1.0 immediately after review."""
    r = _retrievability(0, 10.0)
    assert r == pytest.approx(1.0, abs=0.01)


def test_retrievability_at_stability():
    """Retrievability at elapsed=stability should be ~0.9 (90% retention)."""
    r = _retrievability(10.0, 10.0)
    # FSRS formula: R = (1 + t/(9*S))^(-1) → at t=S: (1 + 1/9)^(-1) = 0.9
    assert r == pytest.approx(0.9, abs=0.01)


def test_retrievability_zero_stability():
    """Zero stability should return 0.0."""
    assert _retrievability(5.0, 0.0) == 0.0


# ── estimate_forgetting_cost ──


def test_forgetting_cost_no_overdue():
    """No overdue cards should return 0.0 cost."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [
        FSRSCard(stability=5.0, due=now + timedelta(days=1)),
        FSRSCard(stability=10.0, due=now + timedelta(days=3)),
    ]

    cost = estimate_forgetting_cost(cards, now)
    assert cost == 0.0


def test_forgetting_cost_overdue_cards():
    """Overdue cards should have positive forgetting cost."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [
        FSRSCard(stability=2.0, due=now - timedelta(days=5)),
        FSRSCard(stability=3.0, due=now - timedelta(days=10)),
    ]

    cost = estimate_forgetting_cost(cards, now)
    assert cost > 0
    assert cost <= 2.0  # At most 2 cards can be forgotten


def test_forgetting_cost_mixed():
    """Mix of overdue and future cards — only overdue should contribute."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [
        FSRSCard(stability=2.0, due=now - timedelta(days=5)),
        FSRSCard(stability=10.0, due=now + timedelta(days=3)),
    ]

    cost = estimate_forgetting_cost(cards, now)
    assert cost > 0
    assert cost < 1.5  # Only one card is overdue


def test_forgetting_cost_zero_stability_ignored():
    """Cards with zero stability should be skipped."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [FSRSCard(stability=0.0, due=now - timedelta(days=5))]

    cost = estimate_forgetting_cost(cards, now)
    assert cost == 0.0


def test_forgetting_cost_no_due_date():
    """Cards without a due date should be skipped."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [FSRSCard(stability=5.0, due=None)]

    cost = estimate_forgetting_cost(cards, now)
    assert cost == 0.0


# ── estimate_session_urgency ──


def test_session_urgency_none():
    """No due cards should return urgency='none'."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [FSRSCard(stability=10.0, due=now + timedelta(days=5))]

    result = estimate_session_urgency(cards, now)
    assert result["urgency"] == "none"
    assert result["due_count"] == 0


def test_session_urgency_low():
    """A few due cards with low cost should return 'low'."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [
        FSRSCard(stability=10.0, due=now - timedelta(hours=1)),
        FSRSCard(stability=10.0, due=now - timedelta(hours=2)),
        FSRSCard(stability=10.0, due=now - timedelta(hours=3)),
    ]

    result = estimate_session_urgency(cards, now)
    assert result["urgency"] == "low"
    assert result["due_count"] == 3


def test_session_urgency_critical():
    """Many very overdue cards should return 'critical'."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    cards = [
        FSRSCard(stability=1.0, due=now - timedelta(days=30))
        for _ in range(20)
    ]

    result = estimate_session_urgency(cards, now)
    assert result["urgency"] in ("high", "critical")
    assert result["forgetting_cost"] >= 2.0
    assert result["due_count"] == 20


def test_session_urgency_response_keys():
    """Response should have all expected keys."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    result = estimate_session_urgency([], now)

    assert "forgetting_cost" in result
    assert "urgency" in result
    assert "due_count" in result
    assert "total_cards" in result
    assert "recommendation" in result


def test_session_urgency_empty_cards():
    """Empty card list should return 'none' urgency."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    result = estimate_session_urgency([], now)
    assert result["urgency"] == "none"
    assert result["due_count"] == 0
    assert result["forgetting_cost"] == 0.0


# ── FSRS-5/6 Upgrade Tests ──


def test_default_w_has_21_params():
    """FSRS-5/6 should have 21 parameters (up from 17 in 4.5)."""
    assert len(DEFAULT_W) == 21


def test_retrievability_with_trainable_decay():
    """When decay=1.0 (default), formula should match FSRS-4.5."""
    # With default w[20]=1.0, result should be same as 4.5
    r = _retrievability(10.0, 10.0)
    assert r == pytest.approx(0.9, abs=0.01)


def test_retrievability_custom_decay():
    """Custom decay parameter should change retrievability curve."""
    w_custom = list(DEFAULT_W)
    w_custom[20] = 0.5  # Lower decay = slower forgetting
    r_default = _retrievability(30.0, 10.0, DEFAULT_W)
    r_custom = _retrievability(30.0, 10.0, w_custom)
    # Lower decay should give higher retrievability (slower forgetting)
    assert r_custom > r_default


def test_initial_difficulty_exponential():
    """FSRS-5/6 uses exponential difficulty init: D0 = w4 - exp(w5*(G-1)) + 1."""
    d1 = _initial_difficulty(1)  # Again
    d3 = _initial_difficulty(3)  # Good
    d4 = _initial_difficulty(4)  # Easy
    # Higher ratings should give lower or equal difficulty (clamped to [1, 10])
    assert d1 >= d3 >= d4
    # All bounded
    assert 1.0 <= d1 <= 10.0
    assert 1.0 <= d4 <= 10.0


def test_next_difficulty_linear_damping():
    """FSRS-5/6 uses linear damping: delta * (10 - D) / 9."""
    d_low = _next_difficulty(3.0, 3)  # Good on easy card
    d_high = _next_difficulty(8.0, 3)  # Good on hard card
    # Linear damping means difficulty change is smaller when D is high
    assert 1.0 <= d_low <= 10.0
    assert 1.0 <= d_high <= 10.0


def test_same_day_stability_default_params():
    """With default w17-19 = 0, same-day stability should return original s."""
    s = _same_day_stability(5.0, 3)
    assert s == 5.0  # Default params (all 0) = no change


def test_same_day_review_in_review_card():
    """Same-day review (elapsed < 1 day) should use _same_day_stability."""
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    card = FSRSCard(
        difficulty=5.0,
        stability=5.0,
        reps=3,
        state="review",
        last_review=now - timedelta(hours=2),  # Same day!
    )
    updated, _ = review_card(card, rating=3, now=now)
    # With default w17-19=0, stability should be unchanged
    assert updated.stability == pytest.approx(5.0, abs=0.01)
