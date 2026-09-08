"""Tests for the cognitive load weight auto-tuner, including concurrent safety (issue #37).

The tuner is reached from FastAPI's threadpool by concurrent chat sessions, so
read-modify-write sequences on the in-memory store must not lose updates and
the eviction scan must not race dict mutation.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from services import cognitive_load_tuning as tuning
from services.cognitive_load_tuning import (
    MIN_WEIGHT_RATIO,
    WEIGHT_DECAY_FACTOR,
    get_multipliers,
    reset_multipliers,
    update_and_get_multipliers,
)


@pytest.fixture(autouse=True)
def _clean_store():
    with tuning._lock:
        tuning._store.clear()
    yield
    with tuning._lock:
        tuning._store.clear()


# ── Sequential behavior ──


def test_no_adjustment_below_min_samples():
    for _ in range(4):
        m = update_and_get_multipliers("u1", {"errors": 1.0})
    assert m["errors"] == 1.0


def test_decay_when_persistently_high():
    # 6 high samples: window reaches 5 on the 5th, so exactly 2 decay steps
    for _ in range(6):
        m = update_and_get_multipliers("u1", {"errors": 1.0})
    assert m["errors"] == pytest.approx(WEIGHT_DECAY_FACTOR ** 2)


def test_decay_floor():
    for _ in range(60):
        m = update_and_get_multipliers("u1", {"errors": 1.0})
    assert m["errors"] == pytest.approx(MIN_WEIGHT_RATIO)


def test_recovery_when_signal_drops():
    for _ in range(60):
        update_and_get_multipliers("u1", {"errors": 1.0})
    for _ in range(60):
        m = update_and_get_multipliers("u1", {"errors": 0.0})
    assert m["errors"] > MIN_WEIGHT_RATIO


def test_reset_multipliers():
    for _ in range(10):
        update_and_get_multipliers("u1", {"errors": 1.0})
    reset_multipliers("u1")
    assert all(v == 1.0 for v in get_multipliers("u1").values())


def test_non_numeric_signals_ignored():
    m = update_and_get_multipliers("u1", {"errors": "high", "fatigue": 0.5})
    assert "errors" not in m and "fatigue" in m


# ── Concurrent safety (issue #37) ──


def test_concurrent_same_signal_loses_no_decay_steps():
    """6 total high samples from 2 threads must yield exactly 2 decay steps.

    Without serialization, two threads can read the same multiplier and both
    write current * 0.9, silently dropping one decay step.
    """
    def worker():
        for _ in range(3):
            update_and_get_multipliers("u1", {"errors": 1.0})

    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in [pool.submit(worker), pool.submit(worker)]:
            f.result()

    assert get_multipliers("u1")["errors"] == pytest.approx(WEIGHT_DECAY_FACTOR ** 2)


def test_concurrent_distinct_signals_all_tracked():
    """Each thread updates its own signal for the same user; none may vanish."""
    def worker(signal):
        for _ in range(6):
            update_and_get_multipliers("u1", {signal: 1.0})

    signals = [f"sig{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for f in [pool.submit(worker, s) for s in signals]:
            f.result()

    m = get_multipliers("u1")
    assert set(m) == set(signals)
    assert all(v == pytest.approx(WEIGHT_DECAY_FACTOR ** 2) for v in m.values())


def test_concurrent_eviction_does_not_crash_or_overflow():
    """480 distinct users from 8 threads cross the 200-user cap concurrently.

    Without the lock, the eviction min() scan iterates the store while other
    threads mutate it (RuntimeError) and parallel inserts overshoot the cap.
    """
    def worker(offset):
        for i in range(60):
            update_and_get_multipliers(f"user-{offset}-{i}", {"errors": 0.5})

    with ThreadPoolExecutor(max_workers=8) as pool:
        for f in [pool.submit(worker, o) for o in range(8)]:
            f.result()  # Raises if any worker crashed

    assert len(tuning._store) <= tuning._MAX_CACHE_SIZE
