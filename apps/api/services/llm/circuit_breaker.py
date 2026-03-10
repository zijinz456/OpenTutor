"""Circuit breaker and progressive cooldown for LLM providers.

Implements:
- Progressive cooldown (openakita pattern): increasing backoff on failures
- Circuit breaker (circuitbreaker pattern): auto-open after N failures,
  auto-reset after timeout
"""

import time
import logging

logger = logging.getLogger(__name__)

# Progressive cooldown steps (borrowed from openakita)
COOLDOWN_STEPS = [5, 10, 20, 60]

# Circuit breaker thresholds
CIRCUIT_OPEN_THRESHOLD = 3  # failures before opening circuit
CIRCUIT_RESET_TIMEOUT = 120  # seconds before trying again


class CircuitBreakerMixin:
    """Health tracking mixin for LLM clients.

    Provides progressive cooldown + circuit breaker logic.
    Mix into any LLMClient subclass.
    """

    provider_name: str = "base"

    def __init__(self):
        self._healthy = True
        self._cooldown_until: float = 0
        self._consecutive_failures: int = 0
        self._circuit_open: bool = False
        self._circuit_open_time: float = 0

    @property
    def is_healthy(self) -> bool:
        # Circuit breaker: auto-reset after timeout
        if self._circuit_open:
            if time.time() - self._circuit_open_time >= CIRCUIT_RESET_TIMEOUT:
                self._circuit_open = False
                self._healthy = True
                self._consecutive_failures = 0
                logger.info(f"Circuit breaker reset for {self.provider_name}")
            else:
                return False

        if self._cooldown_until > 0 and time.time() >= self._cooldown_until:
            self._healthy = True
            self._cooldown_until = 0
        return self._healthy

    def mark_unhealthy(self, error: str):
        """Progressive cooldown + circuit breaker (openakita + circuitbreaker pattern)."""
        self._healthy = False
        self._consecutive_failures += 1

        # Circuit breaker: open after threshold
        if self._consecutive_failures >= CIRCUIT_OPEN_THRESHOLD:
            self._circuit_open = True
            self._circuit_open_time = time.time()
            logger.error(
                f"Circuit OPEN for {self.provider_name} after "
                f"{self._consecutive_failures} failures: {error}"
            )
            return

        idx = min(self._consecutive_failures - 1, len(COOLDOWN_STEPS) - 1)
        cooldown = COOLDOWN_STEPS[idx]
        self._cooldown_until = time.time() + cooldown
        logger.warning(f"LLM {self.provider_name} unhealthy: {error}, cooldown {cooldown}s")

    def mark_healthy(self):
        self._healthy = True
        self._consecutive_failures = 0
        self._cooldown_until = 0
        self._circuit_open = False

    async def ping(self) -> bool:
        """Active liveness check. Override for providers that need probing."""
        return self.is_healthy
