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
