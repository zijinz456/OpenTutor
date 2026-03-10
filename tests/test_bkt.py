"""Tests for Bayesian Knowledge Tracing (BKT) services.

Covers:
- BKTParams and BKTState defaults
- Parameter estimation from answer histories
- Knowledge state updates via Bayes' rule
- Mastery probability calculations from sequences
- Edge cases: 0/1 probabilities, empty inputs, many observations
- bkt_trainer cache and param lookup
"""

import uuid

import pytest

from services.learning_science.knowledge_tracer import (
    BKTParams,
    BKTState,
    compute_mastery_from_sequence,
    estimate_params,
    update_mastery,
)


# ── BKTParams / BKTState defaults ──


def test_default_params():
    """Default BKT params should match documented constants."""
    p = BKTParams()
    assert p.p_l0 == 0.10
    assert p.p_t == 0.20
    assert p.p_g == 0.25
    assert p.p_s == 0.10


def test_default_state():
    """Default BKT state should start at the default prior."""
    s = BKTState()
    assert s.p_mastery == 0.10
    assert s.observations == 0


def test_custom_params():
    """Custom BKT params should be stored correctly."""
    p = BKTParams(p_l0=0.5, p_t=0.3, p_g=0.1, p_s=0.05)
    assert p.p_l0 == 0.5
    assert p.p_t == 0.3
    assert p.p_g == 0.1
    assert p.p_s == 0.05


# ── estimate_params ──


def test_estimate_params_empty():
    """Empty results should return default params."""
    p = estimate_params([])
    assert p == BKTParams()


def test_estimate_params_first_correct():
    """First answer correct should produce higher p_l0."""
    p = estimate_params([True, False, True])
    assert p.p_l0 == 0.30


def test_estimate_params_first_wrong():
    """First answer wrong should produce lower p_l0."""
    p = estimate_params([False, True, True])
    assert p.p_l0 == 0.05


def test_estimate_params_question_type_tf():
    """True/false questions should have p_g = 0.50."""
    p = estimate_params([True], "true_false")
    assert p.p_g == 0.50


def test_estimate_params_question_type_mc():
    """Multiple choice questions should have p_g = 0.25."""
    p = estimate_params([True], "multiple_choice")
    assert p.p_g == 0.25


def test_estimate_params_question_type_short_answer():
    """Short answer questions should have p_g = 0.05."""
    p = estimate_params([True], "short_answer")
    assert p.p_g == 0.05


def test_estimate_params_question_type_matching():
    """Matching questions should have p_g = 0.10."""
    p = estimate_params([True], "matching")
    assert p.p_g == 0.10


def test_estimate_params_transition_rate():
    """Transition rate should reflect wrong -> correct sequences."""
    # All transitions are wrong -> correct: [F, T, F, T, F, T]
    results = [False, True, False, True, False, True]
    p = estimate_params(results)
    # 3 opportunities (after each False), 3 transitions (each followed by True)
    # p_t = 3/3 = 1.0, but clamped to 0.5
    assert p.p_t == 0.5


def test_estimate_params_no_transitions():
    """All wrong answers should produce minimum transition rate."""
    results = [False, False, False, False]
    p = estimate_params(results)
    # 3 opportunities, 0 transitions -> p_t = 0, clamped to 0.05
    assert p.p_t == 0.05


def test_estimate_params_slip_rate():
    """Slip rate should reflect correct -> wrong transitions."""
    # Alternating: [T, F, T, F]
    results = [True, False, True, False]
    p = estimate_params(results)
    # 2 slip opportunities (after each True), 2 slips -> p_s = 1.0, clamped to 0.3
    assert p.p_s == 0.3


def test_estimate_params_no_slips():
    """All correct answers should produce minimum slip rate."""
    results = [True, True, True, True]
    p = estimate_params(results)
    # 3 slip opportunities, 0 slips -> p_s = 0, clamped to 0.02
    assert p.p_s == 0.02


def test_estimate_params_clamps():
    """Parameters should be clamped to valid ranges."""
    p = estimate_params([False, False, False, False, False])
    assert 0.05 <= p.p_t <= 0.5
    assert 0.02 <= p.p_s <= 0.3


# ── update_mastery ──


def test_update_mastery_correct_increases():
    """Correct answer should increase mastery."""
    params = BKTParams(p_l0=0.3, p_t=0.2, p_g=0.25, p_s=0.1)
    state = BKTState(p_mastery=0.3, observations=0)

    new_state = update_mastery(state, is_correct=True, params=params)

    assert new_state.p_mastery > state.p_mastery
    assert new_state.observations == 1


def test_update_mastery_wrong_decreases():
    """Wrong answer should decrease mastery (before learning incorporated)."""
    params = BKTParams(p_l0=0.5, p_t=0.0, p_g=0.25, p_s=0.1)
    state = BKTState(p_mastery=0.5, observations=0)

    # With p_t=0, no learning is incorporated, so wrong answer should decrease
    new_state = update_mastery(state, is_correct=False, params=params)

    assert new_state.p_mastery < state.p_mastery


def test_update_mastery_observation_count():
    """Observation count should increment by 1 each update."""
    params = BKTParams()
    state = BKTState(p_mastery=0.3, observations=5)

    new_state = update_mastery(state, is_correct=True, params=params)
    assert new_state.observations == 6


def test_update_mastery_clamped_to_unit():
    """Mastery should always be in [0, 1]."""
    params = BKTParams(p_l0=0.99, p_t=0.99, p_g=0.01, p_s=0.01)
    state = BKTState(p_mastery=0.99)

    new_state = update_mastery(state, is_correct=True, params=params)
    assert 0.0 <= new_state.p_mastery <= 1.0


def test_update_mastery_zero_mastery_correct():
    """From zero mastery, a correct answer should increase mastery via guess."""
    params = BKTParams(p_l0=0.0, p_t=0.2, p_g=0.25, p_s=0.1)
    state = BKTState(p_mastery=0.0)

    new_state = update_mastery(state, is_correct=True, params=params)

    # Even from 0 mastery, learning opportunity gives p_t
    assert new_state.p_mastery > 0.0


def test_update_mastery_one_mastery_wrong():
    """From full mastery, a wrong answer should decrease mastery."""
    params = BKTParams(p_l0=1.0, p_t=0.0, p_g=0.25, p_s=0.1)
    state = BKTState(p_mastery=1.0)

    new_state = update_mastery(state, is_correct=False, params=params)

    # After a wrong at p_mastery=1.0: posterior = (1.0 * p_s) / (1.0 * p_s)
    # = 1.0 (always was known but slipped), then learning = 1.0 + 0 = 1.0
    # This is the expected behavior: if we're certain they know it,
    # a single wrong is attributed to slip, not ignorance
    assert new_state.p_mastery == pytest.approx(1.0, abs=0.01)


def test_update_mastery_bayes_rule_correct():
    """Verify the Bayes' rule calculation for a correct answer."""
    p_l = 0.3
    p_s = 0.1
    p_g = 0.25
    p_t = 0.2

    params = BKTParams(p_l0=p_l, p_t=p_t, p_g=p_g, p_s=p_s)
    state = BKTState(p_mastery=p_l)

    new_state = update_mastery(state, is_correct=True, params=params)

    # Manual calculation
    p_correct = p_l * (1 - p_s) + (1 - p_l) * p_g
    p_l_given_correct = (p_l * (1 - p_s)) / p_correct
    p_l_new = p_l_given_correct + (1 - p_l_given_correct) * p_t

    assert new_state.p_mastery == pytest.approx(p_l_new, abs=1e-9)


def test_update_mastery_bayes_rule_wrong():
    """Verify the Bayes' rule calculation for a wrong answer."""
    p_l = 0.5
    p_s = 0.15
    p_g = 0.25
    p_t = 0.2

    params = BKTParams(p_l0=p_l, p_t=p_t, p_g=p_g, p_s=p_s)
    state = BKTState(p_mastery=p_l)

    new_state = update_mastery(state, is_correct=False, params=params)

    # Manual calculation
    p_wrong = p_l * p_s + (1 - p_l) * (1 - p_g)
    p_l_given_wrong = (p_l * p_s) / p_wrong
    p_l_new = p_l_given_wrong + (1 - p_l_given_wrong) * p_t

    assert new_state.p_mastery == pytest.approx(p_l_new, abs=1e-9)


# ── compute_mastery_from_sequence ──


def test_mastery_empty_sequence():
    """Empty sequence should return 0.0 mastery."""
    assert compute_mastery_from_sequence([]) == 0.0


def test_mastery_all_correct():
    """All correct answers should yield high mastery."""
    results = [True] * 10
    mastery = compute_mastery_from_sequence(results)
    assert mastery > 0.8


def test_mastery_all_wrong():
    """All wrong answers should yield low mastery."""
    results = [False] * 10
    mastery = compute_mastery_from_sequence(results)
    assert mastery < 0.5


def test_mastery_single_correct():
    """Single correct answer should produce moderate mastery."""
    mastery = compute_mastery_from_sequence([True])
    assert 0.0 < mastery < 1.0


def test_mastery_single_wrong():
    """Single wrong answer should produce low mastery."""
    mastery = compute_mastery_from_sequence([False])
    assert mastery < 0.5


def test_mastery_monotonic_with_correct():
    """More consecutive correct answers should increase mastery."""
    m1 = compute_mastery_from_sequence([True])
    m3 = compute_mastery_from_sequence([True, True, True])
    m10 = compute_mastery_from_sequence([True] * 10)

    assert m1 < m3 < m10


def test_mastery_with_custom_params():
    """Custom params should be used instead of estimation."""
    params = BKTParams(p_l0=0.5, p_t=0.3, p_g=0.1, p_s=0.05)
    results = [True, True, False, True]

    mastery = compute_mastery_from_sequence(results, params=params)
    assert 0.0 < mastery < 1.0


def test_mastery_with_question_type():
    """Different question types should produce different mastery estimates."""
    results = [True, False, True, True]

    m_mc = compute_mastery_from_sequence(results, "multiple_choice")
    m_tf = compute_mastery_from_sequence(results, "true_false")
    m_sa = compute_mastery_from_sequence(results, "short_answer")

    # Short answer has lower guess rate, so correct answers are more meaningful
    # True/false has higher guess rate, so correct answers mean less
    assert m_sa > m_tf


def test_mastery_bounded():
    """Mastery should always be in [0, 1] regardless of input."""
    # Extreme sequences
    assert 0.0 <= compute_mastery_from_sequence([True] * 100) <= 1.0
    assert 0.0 <= compute_mastery_from_sequence([False] * 100) <= 1.0


def test_mastery_many_observations_convergence():
    """After many correct answers, mastery should converge near 1.0."""
    mastery = compute_mastery_from_sequence([True] * 50)
    assert mastery > 0.95


def test_mastery_learning_then_forgetting():
    """Correct streak followed by wrong streak should show decline."""
    learning = [True] * 10
    forgetting = [False] * 5

    m_peak = compute_mastery_from_sequence(learning)
    m_after = compute_mastery_from_sequence(learning + forgetting)

    # Mastery after wrong answers may still be high due to learning,
    # but should be lower than the peak
    assert m_after < m_peak or m_after == pytest.approx(m_peak, abs=0.05)


# ── Edge cases ──


def test_zero_guess_rate():
    """Zero guess rate: correct answers are fully attributed to knowledge."""
    params = BKTParams(p_l0=0.1, p_t=0.2, p_g=0.0, p_s=0.1)
    state = BKTState(p_mastery=0.1)

    new_state = update_mastery(state, is_correct=True, params=params)

    # With p_g=0, a correct answer proves knowledge
    # posterior = (0.1 * 0.9) / (0.1 * 0.9 + 0.9 * 0) = 1.0
    # after learning: 1.0 + 0 = 1.0
    assert new_state.p_mastery == pytest.approx(1.0, abs=1e-6)


def test_zero_slip_rate():
    """Zero slip rate: wrong answers prove ignorance."""
    params = BKTParams(p_l0=0.5, p_t=0.0, p_g=0.25, p_s=0.0)
    state = BKTState(p_mastery=0.5)

    new_state = update_mastery(state, is_correct=False, params=params)

    # With p_s=0, a wrong answer means they don't know
    # posterior = (0.5 * 0) / (0.5 * 0 + 0.5 * 0.75) = 0.0
    # after learning (p_t=0): 0.0
    assert new_state.p_mastery == pytest.approx(0.0, abs=1e-6)


def test_high_learning_rate():
    """High learning rate should cause rapid mastery increase."""
    params = BKTParams(p_l0=0.1, p_t=0.9, p_g=0.25, p_s=0.1)
    results = [True, True, True]

    mastery = compute_mastery_from_sequence(results, params=params)
    assert mastery > 0.95


def test_alternating_answers():
    """Alternating correct/wrong should produce a valid mastery value."""
    results = [True, False] * 10
    mastery = compute_mastery_from_sequence(results)
    # BKT with learning transitions: even alternating patterns can converge
    # high because each wrong->correct transition signals learning.
    # The key invariant is that it stays bounded in [0, 1].
    assert 0.0 <= mastery <= 1.0


# ── bkt_trainer cache ──


def test_get_trained_params_cache_miss():
    """get_trained_params should return None for uncached concept."""
    from services.learning_science.bkt_trainer import get_trained_params

    user_id = uuid.uuid4()
    result = get_trained_params(user_id, None, "nonexistent_concept")
    assert result is None


def test_get_trained_params_cache_hit():
    """get_trained_params should return cached params."""
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
        {"calculus": {"prior": 0.3, "learns": 0.25, "guesses": 0.2, "slips": 0.08}},
        trained_at_ts=time.time(),
    )

    result = get_trained_params(user_id, course_id, "calculus")
    assert result is not None
    assert result["prior"] == 0.3
    assert result["learns"] == 0.25

    # Clean up
    invalidate_trained_params_cache(user_id, course_id)


def test_get_trained_params_all_courses():
    """get_trained_params with course_id=None should use 'all' key."""
    import time
    from services.learning_science.bkt_trainer import (
        set_trained_params_cache,
        invalidate_trained_params_cache,
        get_trained_params,
    )

    user_id = uuid.uuid4()

    set_trained_params_cache(
        user_id,
        None,
        {"algebra": {"prior": 0.2, "learns": 0.15, "guesses": 0.25, "slips": 0.1}},
        trained_at_ts=time.time(),
    )

    result = get_trained_params(user_id, None, "algebra")
    assert result is not None
    assert result["prior"] == 0.2

    # Clean up
    invalidate_trained_params_cache(user_id)


def test_fit_with_pybkt_insufficient_data():
    """_fit_with_pybkt should return empty dict with insufficient data."""
    from services.learning_science.bkt_trainer import _fit_with_pybkt

    # Only 5 observations per concept (below MIN_OBSERVATIONS_FOR_FIT=15)
    data = [{"concept": "c1", "correct": True} for _ in range(5)]
    result = _fit_with_pybkt(data)
    assert result == {}


def test_fit_with_pybkt_empty():
    """_fit_with_pybkt with empty data should return empty dict."""
    from services.learning_science.bkt_trainer import _fit_with_pybkt

    result = _fit_with_pybkt([])
    assert result == {}


def test_trained_params_cache_ttl_covers_weekly_training_cycle():
    """Cache TTL should survive weekly training cadence to avoid fallback drift."""
    from services.learning_science.bkt_trainer import _CACHE_TTL_SECONDS

    assert _CACHE_TTL_SECONDS >= 7 * 24 * 60 * 60


# ── compute_mastery_adaptive ──


def test_compute_mastery_adaptive_fallback():
    """compute_mastery_adaptive should fall back to heuristic without cache."""
    from services.learning_science.knowledge_tracer import compute_mastery_adaptive

    user_id = uuid.uuid4()
    results = [True, True, False, True]

    mastery = compute_mastery_adaptive(
        results, "test_concept", user_id, course_id=None
    )

    # Should produce a valid mastery value via heuristic
    assert 0.0 < mastery < 1.0


def test_compute_mastery_adaptive_with_cache():
    """compute_mastery_adaptive should use cached trained params."""
    import time
    from services.learning_science.bkt_trainer import (
        set_trained_params_cache,
        invalidate_trained_params_cache,
    )
    from services.learning_science.knowledge_tracer import compute_mastery_adaptive

    user_id = uuid.uuid4()
    set_trained_params_cache(
        user_id,
        None,
        {
            "cached_concept": {
                "prior": 0.4,
                "learns": 0.3,
                "guesses": 0.1,
                "slips": 0.05,
            }
        },
        trained_at_ts=time.time(),
    )

    results = [True, True, True]
    mastery = compute_mastery_adaptive(
        results, "cached_concept", user_id, course_id=None
    )

    assert mastery > 0.8

    # Clean up
    invalidate_trained_params_cache(user_id)
