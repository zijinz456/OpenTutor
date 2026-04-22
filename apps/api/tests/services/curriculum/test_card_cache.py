"""Unit tests for ``services.agent.card_cache`` (§14.5 v2.1 T5).

Covers the producer/consumer contract consumed by the orchestrator hook
and the polling endpoint:

* **Happy path.** ``put`` then ``await_or_get`` → returns same cards.
* **Wait-then-signal.** ``await_or_get`` starts first, ``put`` arrives
  mid-wait → consumer wakes and returns cards.
* **Timeout.** ``await_or_get`` with no matching ``put`` → ``None``
  after the timeout elapses.
* **TTL eviction.** Short TTL + sleep past it → subsequent lookup
  returns ``None``.
* **Empty cards.** ``put`` with ``[]`` is a legitimate state distinct
  from "not present" — ``await_or_get`` returns ``[]``, not ``None``.
* **Overwrite.** Two ``put`` calls with the same key — the second value
  wins and re-signals waiters.

Tests manipulate the module-level singleton, so every test resets state
via ``clear()`` in an autouse fixture.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from schemas.curriculum import CardCandidate
from services.agent import card_cache


# ── helpers ─────────────────────────────────────────────────


def _card(front: str = "Q?", back: str = "A.") -> CardCandidate:
    return CardCandidate(front=front, back=back)


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    """Wipe the module-level singleton before each test."""
    card_cache.clear()
    yield
    card_cache.clear()


# ── tests ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_then_await_returns_same_cards() -> None:
    """Fast-path hit: producer fires before consumer waits."""
    sid, mid = uuid.uuid4(), uuid.uuid4()
    cards = [_card("Q1"), _card("Q2")]

    card_cache.put(sid, mid, cards)

    out = await card_cache.await_or_get(sid, mid, timeout_s=0.5)

    assert out is not None
    assert len(out) == 2
    assert [c.front for c in out] == ["Q1", "Q2"]


@pytest.mark.asyncio
async def test_await_then_put_wakes_consumer() -> None:
    """Slow-path: consumer waits, producer fires during the wait.

    Launches both concurrently and schedules ``put`` after a short delay
    so the consumer has already entered ``event.wait()``.
    """
    sid, mid = uuid.uuid4(), uuid.uuid4()
    cards = [_card("Delayed")]

    async def _delayed_put() -> None:
        await asyncio.sleep(0.05)
        card_cache.put(sid, mid, cards)

    consumer_task = asyncio.create_task(
        card_cache.await_or_get(sid, mid, timeout_s=1.0)
    )
    producer_task = asyncio.create_task(_delayed_put())

    out, _ = await asyncio.gather(consumer_task, producer_task)

    assert out is not None
    assert len(out) == 1
    assert out[0].front == "Delayed"


@pytest.mark.asyncio
async def test_await_times_out_when_no_put() -> None:
    """Consumer with no matching producer → None after timeout."""
    sid, mid = uuid.uuid4(), uuid.uuid4()

    start = asyncio.get_event_loop().time()
    out = await card_cache.await_or_get(sid, mid, timeout_s=0.1)
    elapsed = asyncio.get_event_loop().time() - start

    assert out is None
    # Ensure the timeout was actually honoured and we didn't return
    # instantly (which would indicate we mis-handled the "unknown key"
    # branch).
    assert elapsed >= 0.08, f"expected ≥0.08s wait, got {elapsed:.3f}s"
    # And didn't overshoot by much — upper bound guards against a
    # busy-loop implementation.
    assert elapsed < 0.5, f"unexpectedly slow: {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_empty_cards_is_distinct_from_missing() -> None:
    """``put([])`` is a valid "we tried and got zero" outcome."""
    sid, mid = uuid.uuid4(), uuid.uuid4()

    card_cache.put(sid, mid, [])

    out = await card_cache.await_or_get(sid, mid, timeout_s=0.1)

    # Present (not None) and empty.
    assert out == []
    assert out is not None


@pytest.mark.asyncio
async def test_overwrite_updates_and_resignals() -> None:
    """Second ``put`` replaces the first and wakes any fresh waiter."""
    sid, mid = uuid.uuid4(), uuid.uuid4()

    card_cache.put(sid, mid, [_card("v1")])
    card_cache.put(sid, mid, [_card("v2a"), _card("v2b")])

    out = await card_cache.await_or_get(sid, mid, timeout_s=0.1)

    assert out is not None
    assert [c.front for c in out] == ["v2a", "v2b"]


@pytest.mark.asyncio
async def test_ttl_eviction_drops_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """After TTL expiry, the cache no longer reports the entry.

    We can't wait 300s. Instead we swap in a small TTLCache backing
    ``_cache`` so eviction happens within the test budget.
    """
    from cachetools import TTLCache

    # Replace the module singleton with a short-TTL version for the
    # duration of this test. The autouse ``_reset_cache`` fixture will
    # ``clear()`` both stores after; we also restore the original cache
    # here to keep other tests' TTL expectations intact.
    original_cache = card_cache._cache
    short_cache = TTLCache(maxsize=10, ttl=0.1)
    monkeypatch.setattr(card_cache, "_cache", short_cache)

    try:
        sid, mid = uuid.uuid4(), uuid.uuid4()
        card_cache.put(sid, mid, [_card("will-expire")])

        # Sanity — cached now.
        hit = await card_cache.await_or_get(sid, mid, timeout_s=0.05)
        assert hit is not None

        # Wait past TTL then poll again — expect miss+timeout=None.
        await asyncio.sleep(0.2)
        miss = await card_cache.await_or_get(sid, mid, timeout_s=0.1)
        assert miss is None
    finally:
        # Put the full cache back (clean shutdown for autouse fixture).
        monkeypatch.setattr(card_cache, "_cache", original_cache)


@pytest.mark.asyncio
async def test_concurrent_keys_do_not_cross_contaminate() -> None:
    """Two pending waiters on different keys resolve independently."""
    sid = uuid.uuid4()
    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()

    async def _put_a() -> None:
        await asyncio.sleep(0.02)
        card_cache.put(sid, mid_a, [_card("A")])

    async def _put_b() -> None:
        await asyncio.sleep(0.04)
        card_cache.put(sid, mid_b, [_card("B1"), _card("B2")])

    waiters = asyncio.gather(
        card_cache.await_or_get(sid, mid_a, timeout_s=1.0),
        card_cache.await_or_get(sid, mid_b, timeout_s=1.0),
    )
    producers = asyncio.gather(_put_a(), _put_b())

    (out_a, out_b), _ = await asyncio.gather(waiters, producers)

    assert out_a is not None and [c.front for c in out_a] == ["A"]
    assert out_b is not None and [c.front for c in out_b] == ["B1", "B2"]


@pytest.mark.asyncio
async def test_fast_path_is_synchronous_cheap() -> None:
    """When the payload is already cached, ``await_or_get`` should
    return on the first scheduler turn without hitting the 10s timeout.
    Regression guard against accidental busy-loop / long wait."""
    sid, mid = uuid.uuid4(), uuid.uuid4()
    card_cache.put(sid, mid, [_card("instant")])

    start = asyncio.get_event_loop().time()
    out = await card_cache.await_or_get(sid, mid, timeout_s=10.0)
    elapsed = asyncio.get_event_loop().time() - start

    assert out is not None
    # Should be effectively instant — tolerate up to 50ms of scheduler
    # jitter but reject anything approaching the timeout.
    assert elapsed < 0.05, f"fast path took {elapsed:.3f}s"
