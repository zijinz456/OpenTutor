"""FSRS (Free Spaced Repetition Scheduler) implementation.

Upgraded to FSRS-5/6 (21 parameters) from FSRS-4.5 (17 parameters).
30%+ more accurate than Anki's SM-2 algorithm.

Key FSRS-5/6 improvements over 4.5:
- Trainable forgetting curve decay: R(t) = (1 + factor·t/S)^(-decay)
- Same-day review handling: separate stability formula for intra-day reviews
- Exponential difficulty initialization: D0 = w4 - exp(w5·(G-1)) + 1
- Linear damping for difficulty updates

References:
- FSRS-4.5: https://github.com/open-spaced-repetition/fsrs4.5
- FSRS-5/6: https://github.com/open-spaced-repetition/fsrs-rs

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

# FSRS-5/6 default parameters (21 params, upgraded from FSRS-4.5's 17)
DEFAULT_W = [
    0.4, 0.6, 2.4, 5.8,         # w0-w3: initial stability for each rating
    4.93, 0.94, 0.86, 0.01,     # w4-w7: difficulty parameters
    1.49, 0.14, 0.94,           # w8-w10: stability parameters
    2.18, 0.05, 0.34, 1.26,     # w11-w14: retrievability parameters
    0.29, 2.61,                  # w15-w16: hard penalty / easy bonus
    0.0, 0.0, 0.0,              # w17-w19: same-day review parameters (FSRS-5)
    1.0,                         # w20: forgetting curve decay (1.0 = FSRS-4.5 compatible)
]


from libs.datetime_utils import as_utc as _as_utc


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
    """Calculate initial difficulty.

    FSRS-5/6: D0 = w4 - exp(w5 * (G - 1)) + 1
    (FSRS-4.5 used linear: D0 = w4 - (G - 3) * w5)
    """
    d = w[4] - math.exp(w[5] * (rating - 1)) + 1
    return min(max(d, 1.0), 10.0)


def _next_difficulty(d: float, rating: int, w: list[float] = DEFAULT_W) -> float:
    """Calculate next difficulty after a review.

    FSRS-5/6: linear damping D' = D + delta * (10 - D) / 9
    then mean reversion toward D0(4).
    """
    delta_d = -w[6] * (rating - 3)
    d_new = d + delta_d * (10 - d) / 9  # Linear damping (FSRS-5/6)
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


def _same_day_stability(
    s: float,
    rating: int,
    w: list[float] = DEFAULT_W,
) -> float:
    """Calculate stability for same-day reviews (elapsed < 1 day).

    FSRS-5 addition: S' = S * exp(w17 * (G - 3 + w18)) * S^(-w19)
    Prevents stability inflation from multiple intra-day reviews.
    """
    if len(w) <= 19 or (w[17] == 0 and w[18] == 0 and w[19] == 0):
        return s  # Fallback to standard behavior if params not set
    new_s = s * math.exp(w[17] * (rating - 3 + w[18])) * pow(s, -w[19])
    return max(new_s, 0.1)


def _retrievability(elapsed_days: float, stability: float, w: list[float] = DEFAULT_W) -> float:
    """Calculate probability of recall.

    FSRS-5/6: R(t) = (1 + factor * t / S)^(-decay)
    where decay = w[20] (trainable, default 1.0 for FSRS-4.5 compatibility).
    When decay = 1.0, this reduces to the original FSRS-4.5 formula.
    """
    if stability <= 0:
        return 0.0
    decay = w[20] if len(w) > 20 else 1.0
    factor = 9 * decay
    return pow(1 + elapsed_days / (factor * stability), -decay)


def estimate_forgetting_cost(
    cards: list[FSRSCard],
    now: datetime | None = None,
) -> float:
    """Estimate how many cards the student is expected to forget if they don't review now.

    Inspired by Orbit's session batching algorithm:
    For each overdue card, compute expected recall probability using FSRS
    retrievability formula, then sum (1 - R) across all cards.

    Returns:
        float: Expected number of cards that will be forgotten.
        A value >= 2.0 is considered urgent for triggering a proactive review.
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    total_expected_forgotten = 0.0

    for card in cards:
        if card.due is None or card.stability <= 0:
            continue

        due = _as_utc(card.due)
        if due > now:
            continue  # Not yet overdue

        elapsed = max((now - due).total_seconds() / 86400, 0)
        # Use the scheduled interval as baseline
        scheduled_interval = max(card.stability, 1.0)
        # Total elapsed since last review
        total_elapsed = elapsed + scheduled_interval

        recall_prob = _retrievability(total_elapsed, card.stability)
        total_expected_forgotten += (1.0 - recall_prob)

    return round(total_expected_forgotten, 2)


def estimate_session_urgency(
    cards: list[FSRSCard],
    now: datetime | None = None,
) -> dict:
    """Determine review session urgency based on forgetting cost.

    Returns:
        dict with keys:
        - forgetting_cost: float (expected cards forgotten)
        - urgency: "none" | "low" | "normal" | "high" | "critical"
        - due_count: int
        - recommendation: str
    """
    now = _as_utc(now or datetime.now(timezone.utc))
    due_cards = [c for c in cards if c.due and _as_utc(c.due) <= now]
    cost = estimate_forgetting_cost(cards, now)

    if cost >= 5.0:
        urgency = "critical"
        recommendation = "Immediate review needed — significant knowledge loss risk"
    elif cost >= 2.0:
        urgency = "high"
        recommendation = "Review soon — several items at risk of being forgotten"
    elif len(due_cards) >= 10:
        urgency = "normal"
        recommendation = "Good time for a review — enough cards for a full session"
    elif len(due_cards) >= 3:
        urgency = "low"
        recommendation = "A few items due — consider a quick review"
    else:
        urgency = "none"
        recommendation = "No review needed right now"

    return {
        "forgetting_cost": cost,
        "urgency": urgency,
        "due_count": len(due_cards),
        "total_cards": len(cards),
        "recommendation": recommendation,
    }


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
        # Subsequent reviews — compute new values from OLD state before mutating
        r = _retrievability(elapsed_days, card.stability)
        new_d = _next_difficulty(card.difficulty, rating)
        if elapsed_days < 1.0 and card.reps > 0:
            # Same-day review — use FSRS-5 formula to prevent stability inflation
            new_s = _same_day_stability(card.stability, rating)
        else:
            new_s = _next_stability(card.difficulty, card.stability, r, rating)
        card.difficulty = new_d
        card.stability = new_s

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
