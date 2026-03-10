"""Tests for forgetting forecast pure math functions."""

import pytest
from services.spaced_repetition.forgetting_forecast import (
    _retrievability,
    _days_until_retention,
)


class TestRetrievability:
    def test_zero_elapsed_returns_one(self):
        assert _retrievability(0.0, 10.0) == pytest.approx(1.0)

    def test_positive_elapsed(self):
        r = _retrievability(9.0, 1.0)
        # R = (1 + 9/(9*1))^-1 = (1+1)^-1 = 0.5
        assert r == pytest.approx(0.5)

    def test_large_elapsed_low_retrievability(self):
        r = _retrievability(100.0, 1.0)
        assert r < 0.1

    def test_zero_stability_returns_zero(self):
        assert _retrievability(5.0, 0.0) == 0.0

    def test_negative_stability_returns_zero(self):
        assert _retrievability(5.0, -1.0) == 0.0

    def test_bounded_zero_to_one(self):
        for elapsed in [0.0, 1.0, 10.0, 100.0, 1000.0]:
            for stab in [0.1, 1.0, 10.0, 100.0]:
                r = _retrievability(elapsed, stab)
                assert 0.0 <= r <= 1.0


class TestDaysUntilRetention:
    def test_basic_calculation(self):
        # t = 9 * S * (1/R - 1), S=1, R=0.9
        # t = 9 * 1 * (1/0.9 - 1) = 9 * 0.1111 = 1.0
        d = _days_until_retention(1.0, 0.9)
        assert d == pytest.approx(1.0, abs=0.01)

    def test_higher_stability_longer_days(self):
        d1 = _days_until_retention(1.0)
        d2 = _days_until_retention(10.0)
        assert d2 > d1

    def test_zero_stability(self):
        assert _days_until_retention(0.0) == 0.0

    def test_negative_stability(self):
        assert _days_until_retention(-5.0) == 0.0

    def test_threshold_at_one(self):
        assert _days_until_retention(10.0, threshold=1.0) == 0.0

    def test_threshold_at_zero(self):
        assert _days_until_retention(10.0, threshold=0.0) == 0.0

    def test_lower_threshold_longer_days(self):
        d_high = _days_until_retention(10.0, 0.9)
        d_low = _days_until_retention(10.0, 0.5)
        assert d_low > d_high
