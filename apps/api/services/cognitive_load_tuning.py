"""Cognitive load weight auto-tuner — Phase 1.

Maintains a per-user sliding window of recent signal values and adjusts
per-signal weight multipliers when a signal is persistently elevated.

Design rationale
----------------
If a student's error_rate signal is consistently near 1.0 for 20 messages
straight, it's likely a baseline state (not transient overload), so we
gently reduce its weight to prevent score saturation. The adjustment is
small and bounded to preserve interpretability.

This is intentionally simple: no ML, just a sliding window mean + a
small dampening step. Phase 2 can add Bayesian updating if needed.
"""

from __future__ import annotations

import collections
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
WINDOW_SIZE = 20          # Sliding window length (number of load computations)
HIGH_SIGNAL_THRESHOLD = 0.65   # Mean above this → signal is "persistently high"
WEIGHT_DECAY_FACTOR = 0.90     # Multiply weight by this when signal is high
MIN_WEIGHT_RATIO = 0.40        # Weight multiplier floor (don't suppress entirely)
RECOVERY_FACTOR = 1.04         # Nudge weight back up when signal drops below threshold
MAX_WEIGHT_RATIO = 1.0         # Weight multiplier ceiling

# Bounded cache: max number of users to track simultaneously
_MAX_CACHE_SIZE = 200


class _UserState(NamedTuple):
    """Mutable-style tuple replaced on every update."""
    windows: dict[str, collections.deque]   # signal_name → deque of floats
    multipliers: dict[str, float]           # signal_name → current multiplier


# In-memory store: user_id (str) → _UserState
_store: dict[str, _UserState] = {}


def _get_or_create(user_id: str) -> _UserState:
    if user_id not in _store:
        if len(_store) >= _MAX_CACHE_SIZE:
            # Evict the user with the fewest signal updates (least active)
            evict = min(
                _store,
                key=lambda k: sum(len(dq) for dq in _store[k].windows.values()),
            )
            del _store[evict]
        _store[user_id] = _UserState(windows={}, multipliers={})
    return _store[user_id]


def update_and_get_multipliers(
    user_id: str,
    signals: dict[str, float],
) -> dict[str, float]:
    """Record the latest signal snapshot and return adjusted weight multipliers.

    Call this after each ``compute_cognitive_load`` invocation, passing the
    ``signals`` dict it returned.  The returned multipliers can then be applied
    to the config weights before the next computation.

    Example::

        load_result = await compute_cognitive_load(...)
        multipliers = update_and_get_multipliers(str(user_id), load_result["signals"])
        # Next call uses: effective_weight = settings.cognitive_load_weight_X * multipliers.get("X", 1.0)

    Returns a dict mapping signal name → multiplier (float in [MIN_WEIGHT_RATIO, 1.0]).
    For signals with no history yet the multiplier is 1.0 (no adjustment).
    """
    state = _get_or_create(str(user_id))

    for signal_name, value in signals.items():
        if not isinstance(value, (int, float)):
            continue
        if signal_name not in state.windows:
            state.windows[signal_name] = collections.deque(maxlen=WINDOW_SIZE)
            state.multipliers[signal_name] = 1.0

        state.windows[signal_name].append(float(value))

        dq = state.windows[signal_name]
        if len(dq) < 5:
            # Need at least 5 data points before adjusting
            continue

        mean = sum(dq) / len(dq)
        current = state.multipliers[signal_name]

        if mean >= HIGH_SIGNAL_THRESHOLD:
            # Signal persistently high → dampen its weight contribution
            new = max(MIN_WEIGHT_RATIO, current * WEIGHT_DECAY_FACTOR)
            if new != current:
                logger.debug(
                    "cognitive_load_tuning: user=%s signal=%s mean=%.2f → multiplier %.3f → %.3f",
                    user_id, signal_name, mean, current, new,
                )
            state.multipliers[signal_name] = new
        else:
            # Signal no longer elevated → slowly recover toward 1.0
            new = min(MAX_WEIGHT_RATIO, current * RECOVERY_FACTOR)
            state.multipliers[signal_name] = new

    return dict(state.multipliers)


def get_multipliers(user_id: str) -> dict[str, float]:
    """Return the current multipliers for a user without updating the window.

    Returns an empty dict if no data has been recorded for this user yet
    (caller should treat missing keys as multiplier=1.0).
    """
    state = _store.get(str(user_id))
    if state is None:
        return {}
    return dict(state.multipliers)


def reset_multipliers(user_id: str) -> None:
    """Reset all multipliers for a user to 1.0 (e.g. after a long break)."""
    state = _store.get(str(user_id))
    if state is None:
        return
    for key in state.multipliers:
        state.multipliers[key] = 1.0
    for dq in state.windows.values():
        dq.clear()
    logger.info("cognitive_load_tuning: reset multipliers for user=%s", user_id)
