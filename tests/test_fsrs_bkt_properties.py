"""Hypothesis property-based tests for FSRS and BKT math functions.

Tests mathematical invariants that must hold across the entire parameter space:
- Bounds: outputs stay in valid ranges
- Monotonicity: higher ratings produce better outcomes
- Stability: no degenerate values (NaN, Inf, negative)
"""

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from services.spaced_repetition.fsrs import (
    _initial_stability,
    _initial_difficulty,
    _next_difficulty,
    _next_stability,
    _retrievability,
    _same_day_stability,
    DEFAULT_W,
)
from services.learning_science.knowledge_tracer import (
    BKTParams,
    BKTState,
    estimate_params,
    update_mastery,
    compute_mastery_from_sequence,
)


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

rating_st = st.integers(min_value=1, max_value=4)
difficulty_st = st.floats(min_value=1.0, max_value=10.0, allow_nan=False)
stability_st = st.floats(min_value=0.1, max_value=3650.0, allow_nan=False)
retrievability_st = st.floats(min_value=0.01, max_value=1.0, allow_nan=False)
elapsed_st = st.floats(min_value=0.0, max_value=3650.0, allow_nan=False)
probability_st = st.floats(min_value=0.01, max_value=0.99, allow_nan=False)
bool_list_st = st.lists(st.booleans(), min_size=1, max_size=50)
question_type_st = st.sampled_from([None, "mc", "tf", "short_answer", "fill_blank", "matching", "free_response"])


# ===========================================================================
# FSRS Property Tests
# ===========================================================================


class TestFSRSProperties:

    @given(rating=rating_st)
    def test_initial_stability_positive(self, rating):
        s = _initial_stability(rating)
        assert s >= 0.1

    @given(rating=rating_st)
    def test_initial_difficulty_bounded(self, rating):
        d = _initial_difficulty(rating)
        assert 1.0 <= d <= 10.0

    @given(d=difficulty_st, rating=rating_st)
    def test_next_difficulty_bounded(self, d, rating):
        d_new = _next_difficulty(d, rating)
        assert 1.0 <= d_new <= 10.0

    @given(d=difficulty_st, s=stability_st, r=retrievability_st, rating=rating_st)
    def test_next_stability_positive(self, d, s, r, rating):
        s_new = _next_stability(d, s, r, rating)
        assert s_new >= 0.1
        assert not (s_new != s_new)  # not NaN

    @given(elapsed=elapsed_st, s=stability_st)
    def test_retrievability_bounded(self, elapsed, s):
        r = _retrievability(elapsed, s)
        assert 0.0 <= r <= 1.0

    @given(s=stability_st)
    def test_retrievability_at_zero_elapsed_is_one(self, s):
        r = _retrievability(0.0, s)
        assert abs(r - 1.0) < 1e-9

    @given(s=stability_st, e1=elapsed_st, e2=elapsed_st)
    def test_retrievability_decreases_with_time(self, s, e1, e2):
        assume(e1 < e2)
        r1 = _retrievability(e1, s)
        r2 = _retrievability(e2, s)
        assert r1 >= r2

    @given(elapsed=elapsed_st)
    def test_retrievability_zero_stability_is_zero(self, elapsed):
        assert _retrievability(elapsed, 0.0) == 0.0
        assert _retrievability(elapsed, -1.0) == 0.0

    def test_higher_rating_gives_higher_initial_stability(self):
        stabilities = [_initial_stability(r) for r in range(1, 5)]
        for i in range(len(stabilities) - 1):
            assert stabilities[i] <= stabilities[i + 1]

    def test_higher_rating_gives_lower_difficulty(self):
        difficulties = [_initial_difficulty(r) for r in range(1, 5)]
        for i in range(len(difficulties) - 1):
            assert difficulties[i] >= difficulties[i + 1]

    @given(d=difficulty_st, s=stability_st, r=retrievability_st)
    def test_easy_rating_gives_highest_stability(self, d, s, r):
        s_hard = _next_stability(d, s, r, 2)
        s_good = _next_stability(d, s, r, 3)
        s_easy = _next_stability(d, s, r, 4)
        assert s_hard <= s_good <= s_easy


# ===========================================================================
# BKT Property Tests
# ===========================================================================


class TestBKTProperties:

    @given(results=bool_list_st, qt=question_type_st)
    def test_estimate_params_bounded(self, results, qt):
        params = estimate_params(results, qt)
        assert 0.0 <= params.p_l0 <= 1.0
        assert 0.05 <= params.p_t <= 0.5
        assert 0.0 <= params.p_g <= 1.0
        assert 0.02 <= params.p_s <= 0.3

    @given(
        p_mastery=probability_st,
        is_correct=st.booleans(),
        p_l0=probability_st,
        p_t=st.floats(min_value=0.05, max_value=0.5, allow_nan=False),
        p_g=probability_st,
        p_s=st.floats(min_value=0.02, max_value=0.3, allow_nan=False),
    )
    def test_update_mastery_bounded(self, p_mastery, is_correct, p_l0, p_t, p_g, p_s):
        state = BKTState(p_mastery=p_mastery, observations=0)
        params = BKTParams(p_l0=p_l0, p_t=p_t, p_g=p_g, p_s=p_s)
        new_state = update_mastery(state, is_correct, params)
        assert 0.0 <= new_state.p_mastery <= 1.0
        assert new_state.observations == 1

    @given(results=bool_list_st, qt=question_type_st)
    def test_compute_mastery_bounded(self, results, qt):
        m = compute_mastery_from_sequence(results, qt)
        assert 0.0 <= m <= 1.0

    def test_empty_sequence_returns_zero(self):
        assert compute_mastery_from_sequence([]) == 0.0

    @given(n=st.integers(min_value=5, max_value=30))
    def test_all_correct_increases_mastery(self, n):
        results = [True] * n
        m = compute_mastery_from_sequence(results, "mc")
        assert m > 0.5

    @given(n=st.integers(min_value=5, max_value=30))
    def test_all_wrong_keeps_mastery_low(self, n):
        results = [False] * n
        m = compute_mastery_from_sequence(results, "mc")
        assert m < 0.5

    @given(
        p_mastery=probability_st,
        p_t=st.floats(min_value=0.05, max_value=0.5, allow_nan=False),
        p_g=probability_st,
        p_s=st.floats(min_value=0.02, max_value=0.3, allow_nan=False),
    )
    def test_correct_answer_raises_mastery(self, p_mastery, p_t, p_g, p_s):
        assume(p_g < 1 - p_s)  # standard BKT assumption
        state = BKTState(p_mastery=p_mastery)
        params = BKTParams(p_l0=p_mastery, p_t=p_t, p_g=p_g, p_s=p_s)
        after_correct = update_mastery(state, True, params)
        after_wrong = update_mastery(state, False, params)
        assert after_correct.p_mastery >= after_wrong.p_mastery

    @given(results=bool_list_st)
    @settings(max_examples=50)
    def test_mastery_monotone_with_appended_correct(self, results):
        m_before = compute_mastery_from_sequence(results, "mc")
        m_after = compute_mastery_from_sequence(results + [True], "mc")
        assert m_after >= m_before - 1e-9

    def test_guess_rate_by_question_type(self):
        params_tf = estimate_params([True], "tf")
        params_mc = estimate_params([True], "mc")
        params_sa = estimate_params([True], "short_answer")
        assert params_tf.p_g == 0.50
        assert params_mc.p_g == 0.25
        assert params_sa.p_g == 0.05
