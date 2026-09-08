"""FSRS grade-handling and interval edge-case tests (issue #21).

Complements test_fsrs.py (basic scheduling, forgetting cost, urgency) and
test_fsrs_bkt_properties.py (hypothesis invariants) with the gaps called out
in the issue: the Hard grade had zero coverage, and no test pinned the
cross-grade orderings (difficulty, stability, interval) or the
overdue / interval-floor / difficulty-clamp edges.
"""

from datetime import datetime, timedelta, timezone

from services.spaced_repetition.fsrs import (
    DEFAULT_W,
    FSRSCard,
    review_card,
    _initial_difficulty,
    _initial_stability,
    _next_stability,
)

_NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


def _review_state_card(stability=10.0, difficulty=5.0, days_since_review=10):
    return FSRSCard(
        difficulty=difficulty,
        stability=stability,
        reps=3,
        lapses=0,
        state="review",
        last_review=_NOW - timedelta(days=days_since_review),
    )


# ── First review: all four grades ──


def test_first_review_hard_enters_learning():
    card, log = review_card(FSRSCard(), rating=2, now=_NOW)
    assert card.state == "learning"
    assert card.reps == 1 and card.lapses == 0
    assert log.scheduled_days == 1  # Learning cards come back tomorrow
    assert card.due == _NOW + timedelta(days=1)


def test_initial_difficulty_ordering_across_grades():
    # Harder recall (lower grade) must not start with lower difficulty.
    # With DEFAULT_W the Good/Easy values clamp at the 1.0 floor, so the
    # ordering is monotone non-increasing with a strict gap at the top.
    d = [_initial_difficulty(g) for g in (1, 2, 3, 4)]
    assert d[0] > d[1] >= d[2] >= d[3]
    assert all(1.0 <= x <= 10.0 for x in d)


def test_initial_stability_ordering_across_grades():
    s = [_initial_stability(g) for g in (1, 2, 3, 4)]
    assert s[0] < s[1] < s[2] < s[3]
    assert all(x >= 0.1 for x in s)


# ── Subsequent reviews: grade effects ──


def test_hard_penalty_yields_less_stability_growth_than_good():
    s_hard = _next_stability(d=5.0, s=10.0, r=0.9, rating=2)
    s_good = _next_stability(d=5.0, s=10.0, r=0.9, rating=3)
    s_easy = _next_stability(d=5.0, s=10.0, r=0.9, rating=4)
    assert s_hard < s_good < s_easy
    assert s_hard > 10.0  # Hard is still a success: stability must not shrink


def test_interval_ordering_across_grades_on_mature_card():
    intervals = {}
    for grade in (1, 2, 3, 4):
        card, log = review_card(_review_state_card(), rating=grade, now=_NOW)
        intervals[grade] = log.scheduled_days
    assert intervals[1] == 1  # Again always comes back tomorrow
    assert intervals[2] <= intervals[3] <= intervals[4]
    assert intervals[4] > 1


def test_again_on_review_card_lapses_to_relearning():
    card, _ = review_card(_review_state_card(), rating=1, now=_NOW)
    assert card.state == "relearning"
    assert card.lapses == 1
    assert card.due == _NOW + timedelta(days=1)


def test_hard_on_review_card_stays_in_review():
    card, _ = review_card(_review_state_card(), rating=2, now=_NOW)
    assert card.state == "review"
    assert card.lapses == 0


# ── Edge cases ──


def test_overdue_review_still_schedules_forward():
    # 100 days late on a 10-day-stability card: retrievability is tiny, but
    # a Good recall must still grow stability and schedule into the future
    card = _review_state_card(stability=10.0, days_since_review=100)
    updated, log = review_card(card, rating=3, now=_NOW)
    assert updated.stability > 10.0  # Successful recall after deep decay
    assert log.elapsed_days == 100
    assert updated.due > _NOW
    assert log.scheduled_days >= 1


def test_minimum_interval_floor_is_one_day():
    # Tiny stability must never produce a zero/negative interval
    card = _review_state_card(stability=0.2, days_since_review=2)
    _, log = review_card(card, rating=2, now=_NOW)
    assert log.scheduled_days >= 1


def test_difficulty_stays_clamped_under_repeated_failure():
    card = _review_state_card(difficulty=9.5, stability=5.0)
    for i in range(20):
        card, _ = review_card(card, rating=1, now=_NOW + timedelta(days=i + 1))
        assert 1.0 <= card.difficulty <= 10.0
    assert card.lapses == 20


def test_difficulty_stays_clamped_under_repeated_easy():
    card = _review_state_card(difficulty=1.5, stability=5.0)
    now = _NOW
    for i in range(20):
        now = now + timedelta(days=30)
        card, _ = review_card(card, rating=4, now=now)
        assert 1.0 <= card.difficulty <= 10.0


def test_same_day_second_review_inflates_less_than_spaced_review():
    # Two Good reviews 2 hours apart must grow stability less than the same
    # second review after 10 days (FSRS-5 same-day formula)
    base = _review_state_card(stability=10.0)
    same_day, _ = review_card(_review_state_card(stability=10.0), rating=3, now=_NOW)
    same_day, _ = review_card(same_day, rating=3, now=_NOW + timedelta(hours=2))

    spaced, _ = review_card(_review_state_card(stability=10.0), rating=3, now=_NOW)
    spaced, _ = review_card(spaced, rating=3, now=_NOW + timedelta(days=10))

    assert same_day.stability < spaced.stability


def test_naive_datetime_last_review_handled():
    # DB rows can round-trip naive datetimes; review_card must not crash
    card = FSRSCard(
        difficulty=5.0, stability=8.0, reps=2, state="review",
        last_review=datetime(2026, 6, 1, 12, 0),  # naive
    )
    updated, log = review_card(card, rating=3, now=_NOW)
    assert updated.due > _NOW
    assert log.elapsed_days == 9
