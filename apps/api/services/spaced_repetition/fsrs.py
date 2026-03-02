"""FSRS (Free Spaced Repetition Scheduler) implementation.

30%+ more accurate than Anki's SM-2 algorithm.
Reference: spec Phase 2 — py-fsrs + spaceforge patterns.

Core FSRS parameters:
- Difficulty: 1-10 (1 = easiest)
- Stability: days until probability of recall drops to 90%
- Retrievability: probability of recall at current time

Rating scale:
1 = Again (complete failure)
2 = Hard (recalled with significant difficulty)
3 = Good (recalled with some effort)
4 = Easy (recalled effortlessly)
"""

import math
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# FSRS-4.5 default parameters (from research paper)
DEFAULT_W = [
    0.4, 0.6, 2.4, 5.8,  # w0-w3: initial stability for each rating
    4.93, 0.94, 0.86, 0.01,  # w4-w7: difficulty parameters
    1.49, 0.14, 0.94,  # w8-w10: stability parameters
    2.18, 0.05, 0.34, 1.26,  # w11-w14: retrievability parameters
    0.29, 2.61,  # w15-w16: additional parameters
]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass
class FSRSCard:
    """A card in the FSRS system."""
    difficulty: float = 5.0  # 1-10
    stability: float = 0.0  # days
    reps: int = 0
    lapses: int = 0
    last_review: datetime | None = None
    due: datetime | None = None
    state: str = "new"  # new, learning, review, relearning


@dataclass
class ReviewLog:
    """Result of a review."""
    rating: int  # 1-4
    scheduled_days: int
    elapsed_days: int
    state: str
    review_time: datetime


def _initial_stability(rating: int, w: list[float] = DEFAULT_W) -> float:
    """Calculate initial stability for first review."""
    return max(w[rating - 1], 0.1)


def _initial_difficulty(rating: int, w: list[float] = DEFAULT_W) -> float:
    """Calculate initial difficulty."""
    d = w[4] - (rating - 3) * w[5]
    return min(max(d, 1.0), 10.0)


def _next_difficulty(d: float, rating: int, w: list[float] = DEFAULT_W) -> float:
    """Calculate next difficulty after a review."""
    delta_d = -w[6] * (rating - 3)
    d_new = d + delta_d
    # Mean reversion
    d_new = w[7] * _initial_difficulty(4, w) + (1 - w[7]) * d_new
    return min(max(d_new, 1.0), 10.0)


def _next_stability(
    d: float,
    s: float,
    r: float,
    rating: int,
    w: list[float] = DEFAULT_W,
) -> float:
    """Calculate next stability after a successful review."""
    if rating == 1:  # Again — lapse
        return max(
            w[11] * pow(d, -w[12]) * (pow(s + 1, w[13]) - 1) * math.exp((1 - r) * w[14]),
            0.1,
        )

    # Good/Hard/Easy
    hard_penalty = w[15] if rating == 2 else 1.0
    easy_bonus = w[16] if rating == 4 else 1.0

    new_s = s * (
        1 + math.exp(w[8])
        * (11 - d)
        * pow(s, -w[9])
        * (math.exp((1 - r) * w[10]) - 1)
        * hard_penalty
        * easy_bonus
    )

    return max(new_s, 0.1)


def _retrievability(elapsed_days: float, stability: float) -> float:
    """Calculate probability of recall."""
    if stability <= 0:
        return 0.0
    return pow(1 + elapsed_days / (9 * stability), -1)


def review_card(
    card: FSRSCard,
    rating: int,
    now: datetime | None = None,
) -> tuple[FSRSCard, ReviewLog]:
    """Process a review and return updated card + log.

    Rating: 1=Again, 2=Hard, 3=Good, 4=Easy
    """
    now = _as_utc(now or datetime.now(timezone.utc))

    # Calculate elapsed days since last review
    if card.last_review:
        elapsed_days = max((now - _as_utc(card.last_review)).total_seconds() / 86400, 0)
    else:
        elapsed_days = 0

    old_state = card.state

    if card.state == "new" or card.reps == 0:
        # First review
        card.difficulty = _initial_difficulty(rating)
        card.stability = _initial_stability(rating)
        card.state = "learning" if rating < 3 else "review"
    else:
        # Subsequent reviews
        r = _retrievability(elapsed_days, card.stability)
        card.difficulty = _next_difficulty(card.difficulty, rating)
        card.stability = _next_stability(card.difficulty, card.stability, r, rating)

        if rating == 1:
            card.lapses += 1
            card.state = "relearning"
        else:
            card.state = "review"

    card.reps += 1
    card.last_review = now

    # Calculate interval
    if rating == 1:
        scheduled_days = 1  # See again tomorrow
    elif card.state == "learning":
        scheduled_days = 1
    else:
        # FSRS: interval = stability * desired_retention_factor
        # For 90% retention: interval ≈ stability
        scheduled_days = max(1, round(card.stability))

    card.due = now + timedelta(days=scheduled_days)

    log = ReviewLog(
        rating=rating,
        scheduled_days=scheduled_days,
        elapsed_days=round(elapsed_days),
        state=old_state,
        review_time=now,
    )

    return card, log
