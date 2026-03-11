"""Tests for the CircuitBreakerMixin."""

import time
from unittest.mock import patch

import pytest

from services.llm.circuit_breaker import (
    CIRCUIT_OPEN_THRESHOLD,
    CIRCUIT_RESET_TIMEOUT,
    COOLDOWN_STEPS,
    CircuitBreakerMixin,
)


class DummyProvider(CircuitBreakerMixin):
    provider_name = "test"

    def __init__(self):
        super().__init__()


@pytest.fixture
def cb():
    return DummyProvider()


# 1. Initially healthy
def test_initially_healthy(cb):
    assert cb.is_healthy is True
    assert cb._consecutive_failures == 0
    assert cb._circuit_open is False


# 2. Single failure -> unhealthy with 5s cooldown
def test_single_failure_unhealthy_with_cooldown(cb):
    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now
        cb.mark_unhealthy("error")

    assert cb._healthy is False
    assert cb._consecutive_failures == 1
    assert cb._cooldown_until == pytest.approx(now + COOLDOWN_STEPS[0], abs=0.1)
    assert cb._circuit_open is False


# 3. Progressive cooldown: 1st=5s, 2nd=10s, 3rd opens circuit
def test_progressive_cooldown(cb):
    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now

        # 1st failure: 5s cooldown
        cb.mark_unhealthy("err1")
        assert cb._cooldown_until == pytest.approx(now + 5, abs=0.1)
        assert cb._circuit_open is False

        # 2nd failure: 10s cooldown
        cb.mark_unhealthy("err2")
        assert cb._cooldown_until == pytest.approx(now + 10, abs=0.1)
        assert cb._circuit_open is False

        # 3rd failure: circuit opens (no cooldown set, circuit takes over)
        cb.mark_unhealthy("err3")
        assert cb._circuit_open is True
        assert cb._consecutive_failures == CIRCUIT_OPEN_THRESHOLD


# 4. Circuit opens after CIRCUIT_OPEN_THRESHOLD failures
def test_circuit_opens_at_threshold(cb):
    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now
        for i in range(CIRCUIT_OPEN_THRESHOLD):
            cb.mark_unhealthy(f"error {i}")

    assert cb._circuit_open is True
    assert cb._consecutive_failures == CIRCUIT_OPEN_THRESHOLD

    # While circuit is open, is_healthy returns False
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now + 1  # well within timeout
        assert cb.is_healthy is False


# 5. Circuit auto-resets after CIRCUIT_RESET_TIMEOUT
def test_circuit_auto_resets_after_timeout(cb):
    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now
        for i in range(CIRCUIT_OPEN_THRESHOLD):
            cb.mark_unhealthy(f"error {i}")

    assert cb._circuit_open is True

    # Simulate time passing beyond the reset timeout
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now + CIRCUIT_RESET_TIMEOUT + 1
        assert cb.is_healthy is True

    # State should be fully reset
    assert cb._circuit_open is False
    assert cb._healthy is True
    assert cb._consecutive_failures == 0


# 6. mark_healthy resets all state
def test_mark_healthy_resets_all_state(cb):
    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now
        for i in range(CIRCUIT_OPEN_THRESHOLD):
            cb.mark_unhealthy(f"error {i}")

    assert cb._circuit_open is True
    assert cb._consecutive_failures == CIRCUIT_OPEN_THRESHOLD
    assert cb._healthy is False

    cb.mark_healthy()

    assert cb._healthy is True
    assert cb._consecutive_failures == 0
    assert cb._cooldown_until == 0
    assert cb._circuit_open is False


# 7. Cooldown expiry restores health
def test_cooldown_expiry_restores_health(cb):
    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now
        cb.mark_unhealthy("error")

    assert cb._healthy is False
    cooldown = COOLDOWN_STEPS[0]

    # Before cooldown expires: still unhealthy
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now + cooldown - 1
        assert cb.is_healthy is False

    # After cooldown expires: healthy again
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now + cooldown + 1
        assert cb.is_healthy is True

    assert cb._healthy is True
    assert cb._cooldown_until == 0


# 8. Circuit open returns False even if _healthy is somehow True
def test_circuit_open_overrides_healthy_flag(cb):
    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now
        for i in range(CIRCUIT_OPEN_THRESHOLD):
            cb.mark_unhealthy(f"error {i}")

    # Force _healthy to True manually
    cb._healthy = True
    assert cb._circuit_open is True

    # Circuit open should still make is_healthy return False
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now + 1  # within timeout
        assert cb.is_healthy is False


# Bonus: ping delegates to is_healthy
@pytest.mark.asyncio
async def test_ping_delegates_to_is_healthy(cb):
    assert await cb.ping() is True

    now = time.time()
    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now
        cb.mark_unhealthy("err")

    with patch("services.llm.circuit_breaker.time") as mock_time:
        mock_time.time.return_value = now  # still in cooldown
        assert await cb.ping() is False
