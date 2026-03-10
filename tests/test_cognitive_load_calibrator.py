"""Tests for services/cognitive_load_calibrator.py — per-student baseline calibration."""

import uuid
import pytest
from services.cognitive_load_calibrator import (
    StudentBaseline,
    get_or_create_baseline,
    compute_relative_load,
    _baselines,
    CALIBRATION_MIN_MESSAGES,
    BREVITY_SEVERE_SIGNAL,
    BREVITY_MODERATE_SIGNAL,
    UNUSUAL_HELP_SIGNAL,
)


@pytest.fixture(autouse=True)
def clear_baselines():
    _baselines.clear()
    yield
    _baselines.clear()


class TestStudentBaseline:
    def test_not_calibrated_initially(self):
        b = StudentBaseline(user_id="u1")
        assert not b.is_calibrated
        assert b.message_count == 0

    def test_calibrated_after_threshold(self):
        b = StudentBaseline(user_id="u1")
        for i in range(CALIBRATION_MIN_MESSAGES):
            b.update(f"message {i}", is_help_seeking=False)
        assert b.is_calibrated

    def test_update_computes_averages(self):
        b = StudentBaseline(user_id="u1")
        b.update("hello", is_help_seeking=False)
        assert b.avg_message_length == 5.0
        assert b.avg_word_count == 1.0
        assert b.help_seeking_rate == 0.0

        b.update("hi there friend", is_help_seeking=True)
        assert b.message_count == 2
        assert b.avg_message_length == (5 + 15) / 2
        assert b.help_seeking_rate == 0.5


class TestGetOrCreateBaseline:
    def test_creates_new(self):
        uid = uuid.uuid4()
        b = get_or_create_baseline(uid)
        assert b.user_id == str(uid)
        assert b.message_count == 0

    def test_returns_existing(self):
        uid = uuid.uuid4()
        b1 = get_or_create_baseline(uid)
        b1.update("test", False)
        b2 = get_or_create_baseline(uid)
        assert b2.message_count == 1


class TestComputeRelativeLoad:
    def _calibrated_baseline(self, avg_len=100.0, help_rate=0.05):
        b = StudentBaseline(user_id="u1")
        # Manually set calibrated state
        b.message_count = CALIBRATION_MIN_MESSAGES
        b.avg_message_length = avg_len
        b.help_seeking_rate = help_rate
        return b

    def test_uncalibrated_returns_no_adjustments(self):
        b = StudentBaseline(user_id="u1")
        result = compute_relative_load(b, 50, False)
        assert result["calibrated"] is False
        assert result["adjustments"] == {}

    def test_severe_brevity(self):
        b = self._calibrated_baseline(avg_len=100.0)
        result = compute_relative_load(b, 30, False)  # 30% of avg
        assert result["calibrated"] is True
        assert result["adjustments"]["relative_brevity"] == BREVITY_SEVERE_SIGNAL

    def test_moderate_brevity(self):
        b = self._calibrated_baseline(avg_len=100.0)
        result = compute_relative_load(b, 60, False)  # 60% of avg
        assert result["adjustments"]["relative_brevity"] == BREVITY_MODERATE_SIGNAL

    def test_normal_length(self):
        b = self._calibrated_baseline(avg_len=100.0)
        result = compute_relative_load(b, 80, False)  # 80% of avg
        assert result["adjustments"]["relative_brevity"] == 0.0

    def test_unusual_help_seeking(self):
        b = self._calibrated_baseline(help_rate=0.05)  # rarely seeks help
        result = compute_relative_load(b, 100, True)
        assert result["adjustments"]["unusual_help_seeking"] == UNUSUAL_HELP_SIGNAL

    def test_normal_help_seeking(self):
        b = self._calibrated_baseline(help_rate=0.05)
        result = compute_relative_load(b, 100, False)
        assert result["adjustments"]["unusual_help_seeking"] == 0.0

    def test_frequent_help_seeker_not_flagged(self):
        b = self._calibrated_baseline(help_rate=0.3)  # frequently seeks help
        result = compute_relative_load(b, 100, True)
        assert result["adjustments"]["unusual_help_seeking"] == 0.0
