"""Unit tests for ``services.drill_runner.run_drill`` (Phase 16c T6).

Covers the three verdict branches the router/submission layer relies on:

1. ``test_run_drill_pass`` — reference solution that actually satisfies
   its own hidden_tests → ``passed=True``.
2. ``test_run_drill_fail`` — stub solution that fails the hidden test
   → ``passed=False`` with pytest output captured.
3. ``test_run_drill_timeout`` — infinite loop gets killed inside the
   5s timeout and returns a one-line "timeout after Ns" message.

Tests spawn real subprocesses (same pattern as the loader's
reference-solution gate). Total suite cost ≈ 2-3s.
"""

from __future__ import annotations

import pytest

from services.drill_runner import _truncate, run_drill


_PASS_SOLUTION = """\
def add(a, b):
    return a + b
"""

_FAIL_SOLUTION = """\
def add(a, b):
    return a - b  # wrong — failing branch
"""

_HIDDEN_TESTS = """\
from solution import add

def test_simple_sum():
    assert add(2, 3) == 5

def test_negative():
    assert add(-1, 1) == 0
"""


@pytest.mark.asyncio
async def test_run_drill_pass():
    """Correct solution → ``passed=True`` + non-negative duration."""

    result = await run_drill(_PASS_SOLUTION, _HIDDEN_TESTS, timeout_s=10.0)

    assert result.passed is True
    assert result.duration_ms >= 0


@pytest.mark.asyncio
async def test_run_drill_fail():
    """Wrong solution → ``passed=False`` and pytest output present."""

    result = await run_drill(_FAIL_SOLUTION, _HIDDEN_TESTS, timeout_s=10.0)

    assert result.passed is False
    # Runner output carries pytest's captured summary. We don't pin the
    # exact string (pytest versions drift) but the literal "assert" must
    # appear because the failure shows the assertion line.
    assert "assert" in result.output.lower()


@pytest.mark.asyncio
async def test_run_drill_timeout():
    """Infinite loop is killed inside the timeout and reported cleanly."""

    infinite_loop = "while True: pass\n"
    result = await run_drill(infinite_loop, _HIDDEN_TESTS, timeout_s=1.0)

    assert result.passed is False
    assert "timeout" in result.output.lower()


def test_truncate_preserves_tail():
    """Tail-preserving truncation: keep the end, prefix a marker."""

    # 20 KB of filler + a distinctive tail marker
    payload = ("x" * 20_000) + "TAIL_MARKER"
    out = _truncate(payload)

    # Truncated by ~12 KB, but the tail (and marker) survive
    assert out.startswith("...[truncated]...")
    assert out.endswith("TAIL_MARKER")


def test_truncate_passthrough_under_cap():
    """Output under the 8 KB cap is returned verbatim."""

    payload = "small output\n"
    assert _truncate(payload) == payload
