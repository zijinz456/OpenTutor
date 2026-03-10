"""Per-student cognitive load baseline calibration.

During the first N sessions, establish baseline behavior metrics:
- Average message length
- Average response time (time between messages)
- Vocabulary diversity
- Help-seeking frequency

Subsequent load scores are relative to individual baseline.
"""
import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)

# Calibration thresholds (named constants instead of magic numbers)
CALIBRATION_MIN_MESSAGES = 20        # Messages needed before baseline is calibrated
BREVITY_SEVERE_RATIO = 0.5          # Length ratio below this = strong brevity signal
BREVITY_MODERATE_RATIO = 0.7        # Length ratio below this = moderate brevity signal
BREVITY_SEVERE_SIGNAL = 0.3         # Signal strength for severe brevity
BREVITY_MODERATE_SIGNAL = 0.15      # Signal strength for moderate brevity
UNUSUAL_HELP_RATE_THRESHOLD = 0.1   # Below this rate = student rarely seeks help
UNUSUAL_HELP_SIGNAL = 0.2           # Signal strength for unusual help-seeking

# In-memory baselines (would be persisted in production)
_baselines: dict[str, "StudentBaseline"] = {}


@dataclass
class StudentBaseline:
    """Baseline behavioral metrics for a student."""

    user_id: str
    avg_message_length: float = 0.0
    avg_word_count: float = 0.0
    help_seeking_rate: float = 0.0
    session_count: int = 0
    message_count: int = 0
    # Running accumulators
    _total_length: float = 0.0
    _total_words: float = 0.0
    _help_count: int = 0

    @property
    def is_calibrated(self) -> bool:
        return self.message_count >= CALIBRATION_MIN_MESSAGES

    def update(self, message: str, is_help_seeking: bool) -> None:
        self.message_count += 1
        self._total_length += len(message)
        self._total_words += len(message.split())
        if is_help_seeking:
            self._help_count += 1

        # Update running averages
        self.avg_message_length = self._total_length / self.message_count
        self.avg_word_count = self._total_words / self.message_count
        self.help_seeking_rate = self._help_count / self.message_count


def get_or_create_baseline(user_id: uuid.UUID) -> StudentBaseline:
    key = str(user_id)
    if key not in _baselines:
        _baselines[key] = StudentBaseline(user_id=key)
    return _baselines[key]


def compute_relative_load(
    baseline: StudentBaseline,
    current_message_length: int,
    current_is_help_seeking: bool,
) -> dict:
    """Compute cognitive load signals relative to individual baseline.

    Returns adjustment factors that can be added to the standard signals.
    """
    if not baseline.is_calibrated:
        return {"calibrated": False, "adjustments": {}}

    adjustments = {}

    # Brevity relative to baseline
    if baseline.avg_message_length > 0:
        length_ratio = current_message_length / baseline.avg_message_length
        if length_ratio < BREVITY_SEVERE_RATIO:
            adjustments["relative_brevity"] = BREVITY_SEVERE_SIGNAL
        elif length_ratio < BREVITY_MODERATE_RATIO:
            adjustments["relative_brevity"] = BREVITY_MODERATE_SIGNAL
        else:
            adjustments["relative_brevity"] = 0.0

    # Help-seeking relative to baseline
    if baseline.help_seeking_rate < UNUSUAL_HELP_RATE_THRESHOLD and current_is_help_seeking:
        # Student rarely asks for help but is doing so now
        adjustments["unusual_help_seeking"] = UNUSUAL_HELP_SIGNAL
    else:
        adjustments["unusual_help_seeking"] = 0.0

    return {
        "calibrated": True,
        "baseline_messages": baseline.message_count,
        "adjustments": adjustments,
    }
