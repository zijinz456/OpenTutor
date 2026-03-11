"""Per-student cognitive load baseline calibration.

During the first N sessions, establish baseline behavior metrics:
- Average message length
- Average response time (time between messages)
- Vocabulary diversity
- Help-seeking frequency

Subsequent load scores are relative to individual baseline.
Baselines are persisted to the database and cached in-memory.
"""
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Calibration thresholds (named constants instead of magic numbers)
CALIBRATION_MIN_MESSAGES = 20        # Messages needed before baseline is calibrated
BREVITY_SEVERE_RATIO = 0.5          # Length ratio below this = strong brevity signal
BREVITY_MODERATE_RATIO = 0.7        # Length ratio below this = moderate brevity signal
BREVITY_SEVERE_SIGNAL = 0.3         # Signal strength for severe brevity
BREVITY_MODERATE_SIGNAL = 0.15      # Signal strength for moderate brevity
UNUSUAL_HELP_RATE_THRESHOLD = 0.1   # Below this rate = student rarely seeks help
UNUSUAL_HELP_SIGNAL = 0.2           # Signal strength for unusual help-seeking

# Drift detection constants (Track 2.5)
DRIFT_EMA_ALPHA = 0.1                # EMA smoothing factor (~last 10 messages)
DRIFT_RATIO_THRESHOLD = 0.6          # EMA/baseline ratio below this = drift
DRIFT_SUSTAINED_COUNT = 10           # Consecutive drift messages before flag
DRIFT_LOAD_BOOST = 0.2               # Extra cognitive load when drift detected

# Flush to DB every N updates to avoid excessive writes
_FLUSH_INTERVAL = 5

# In-memory cache (avoids DB read on every message).
# Bounded to prevent unbounded memory growth with many students.
_MAX_CACHE_SIZE = 200
_cache: dict[str, "StudentBaseline"] = {}


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
    # Dirty tracking for DB flush
    _updates_since_flush: int = 0
    # Drift detection — EMA of recent message lengths (Track 2.5)
    _ema_length: float = 0.0
    _drift_counter: int = 0  # Consecutive messages where EMA < 60% of baseline

    @property
    def is_calibrated(self) -> bool:
        return self.message_count >= CALIBRATION_MIN_MESSAGES

    @property
    def drift_detected(self) -> bool:
        """True if recent messages are significantly shorter than baseline (sustained)."""
        return self._drift_counter >= DRIFT_SUSTAINED_COUNT

    def update(self, message: str, is_help_seeking: bool) -> None:
        self.message_count += 1
        msg_len = len(message)
        self._total_length += msg_len
        self._total_words += len(message.split())
        if is_help_seeking:
            self._help_count += 1

        # Update running averages
        self.avg_message_length = self._total_length / self.message_count
        self.avg_word_count = self._total_words / self.message_count
        self.help_seeking_rate = self._help_count / self.message_count
        self._updates_since_flush += 1

        # Update EMA for drift detection (alpha=0.1, responds to last ~10 msgs)
        if self._ema_length == 0.0:
            self._ema_length = float(msg_len)
        else:
            self._ema_length = DRIFT_EMA_ALPHA * msg_len + (1 - DRIFT_EMA_ALPHA) * self._ema_length

        # Track drift: EMA < 60% of overall baseline for sustained count
        if self.is_calibrated and self.avg_message_length > 0:
            ratio = self._ema_length / self.avg_message_length
            if ratio < DRIFT_RATIO_THRESHOLD:
                self._drift_counter += 1
            else:
                self._drift_counter = max(0, self._drift_counter - 1)

    @property
    def needs_flush(self) -> bool:
        return self._updates_since_flush >= _FLUSH_INTERVAL


def get_or_create_baseline(user_id: uuid.UUID) -> StudentBaseline:
    """Get baseline from in-memory cache (sync, no DB)."""
    key = str(user_id)
    if key not in _cache:
        # Evict oldest entries if cache is full
        if len(_cache) >= _MAX_CACHE_SIZE:
            # Remove the entry with fewest messages (least active student)
            evict_key = min(_cache, key=lambda k: _cache[k].message_count)
            del _cache[evict_key]
        _cache[key] = StudentBaseline(user_id=key)
    return _cache[key]


async def load_baseline_from_db(db: AsyncSession, user_id: uuid.UUID) -> StudentBaseline:
    """Load baseline from DB into cache. Call once at session start."""
    key = str(user_id)
    if key in _cache and _cache[key].message_count > 0:
        return _cache[key]

    try:
        from models.cognitive_baseline import CognitiveBaseline

        result = await db.execute(
            select(CognitiveBaseline).where(CognitiveBaseline.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row:
            baseline = StudentBaseline(
                user_id=key,
                avg_message_length=row.avg_message_length,
                avg_word_count=row.avg_word_count,
                help_seeking_rate=row.help_seeking_rate,
                session_count=row.session_count,
                message_count=row.message_count,
                _total_length=row.total_length,
                _total_words=row.total_words,
                _help_count=row.help_count,
            )
            # Respect cache size bound
            if len(_cache) >= _MAX_CACHE_SIZE:
                evict_key = min(_cache, key=lambda k: _cache[k].message_count)
                del _cache[evict_key]
            _cache[key] = baseline
            return baseline
    except (SQLAlchemyError, OSError) as e:
        logger.warning("Failed to load cognitive baseline from DB: %s", e)

    return get_or_create_baseline(user_id)


async def resolve_baseline(db: AsyncSession, user_id: uuid.UUID) -> StudentBaseline:
    """Compatibility resolver for baseline loading.

    Migration path:
    - Legacy callers/tests patch `get_or_create_baseline`
    - New runtime path prefers persisted DB baselines
    """
    baseline = get_or_create_baseline(user_id)
    message_count = getattr(baseline, "message_count", 0)
    try:
        needs_hydrate = int(message_count) <= 0
    except (TypeError, ValueError):
        # Non-numeric mock/patch values: keep legacy baseline object as-is.
        needs_hydrate = False

    if not needs_hydrate:
        return baseline
    return await load_baseline_from_db(db, user_id)


async def flush_baseline_to_db(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Persist current baseline to DB. Call periodically or at session end."""
    key = str(user_id)
    baseline = _cache.get(key)
    if not baseline or baseline._updates_since_flush == 0:
        return

    try:
        from models.cognitive_baseline import CognitiveBaseline

        result = await db.execute(
            select(CognitiveBaseline).where(CognitiveBaseline.user_id == user_id)
        )
        row = result.scalar_one_or_none()

        if row:
            row.avg_message_length = baseline.avg_message_length
            row.avg_word_count = baseline.avg_word_count
            row.help_seeking_rate = baseline.help_seeking_rate
            row.message_count = baseline.message_count
            row.session_count = baseline.session_count
            row.total_length = baseline._total_length
            row.total_words = baseline._total_words
            row.help_count = baseline._help_count
        else:
            row = CognitiveBaseline(
                user_id=user_id,
                avg_message_length=baseline.avg_message_length,
                avg_word_count=baseline.avg_word_count,
                help_seeking_rate=baseline.help_seeking_rate,
                message_count=baseline.message_count,
                session_count=baseline.session_count,
                total_length=baseline._total_length,
                total_words=baseline._total_words,
                help_count=baseline._help_count,
            )
            db.add(row)

        await db.flush()
        baseline._updates_since_flush = 0
    except (SQLAlchemyError, OSError) as e:
        logger.warning("Failed to flush cognitive baseline to DB: %s", e)


def compute_relative_load(
    baseline: StudentBaseline,
    current_message_length: int,
    current_is_help_seeking: bool,
    current_word_count: int = 0,
) -> dict:
    """Compute cognitive load signals relative to individual baseline.

    Returns adjustment factors that can be added to the standard signals.
    """
    if not baseline.is_calibrated:
        return {"calibrated": False, "adjustments": {}}

    adjustments = {}

    # Brevity relative to baseline (character length)
    if baseline.avg_message_length > 0:
        length_ratio = current_message_length / baseline.avg_message_length
        if length_ratio < BREVITY_SEVERE_RATIO:
            adjustments["relative_brevity"] = BREVITY_SEVERE_SIGNAL
        elif length_ratio < BREVITY_MODERATE_RATIO:
            adjustments["relative_brevity"] = BREVITY_MODERATE_SIGNAL
        else:
            adjustments["relative_brevity"] = 0.0

    # Word count drop relative to baseline — low word count may indicate
    # disengagement or terse frustration responses
    if baseline.avg_word_count > 0 and current_word_count > 0:
        word_ratio = current_word_count / baseline.avg_word_count
        if word_ratio < BREVITY_SEVERE_RATIO:
            adjustments["relative_word_brevity"] = BREVITY_SEVERE_SIGNAL
        elif word_ratio < BREVITY_MODERATE_RATIO:
            adjustments["relative_word_brevity"] = BREVITY_MODERATE_SIGNAL
        else:
            adjustments["relative_word_brevity"] = 0.0

    # Help-seeking relative to baseline
    if baseline.help_seeking_rate < UNUSUAL_HELP_RATE_THRESHOLD and current_is_help_seeking:
        # Student rarely asks for help but is doing so now
        adjustments["unusual_help_seeking"] = UNUSUAL_HELP_SIGNAL
    else:
        adjustments["unusual_help_seeking"] = 0.0

    # Drift detection: sustained shortening of messages
    if baseline.drift_detected:
        adjustments["baseline_drift"] = DRIFT_LOAD_BOOST

    return {
        "calibrated": True,
        "baseline_messages": baseline.message_count,
        "adjustments": adjustments,
    }
