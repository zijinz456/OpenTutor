"""Unit tests for ``routers.curriculum.get_card_candidates`` (§14.5 T5).

Covers the three observable branches of the endpoint:

1. **Already cached** — ``put`` ran before the endpoint is hit → returns
   the cards immediately with ``reason=None``.
2. **Timeout** — no ``put`` ever happens → endpoint returns
   ``{cards:[], reason:"no_candidates"}``.
3. **In-flight then resolves** — a ``put`` lands during the endpoint's
   wait window → endpoint returns the fresh cards (reason None).

The endpoint itself doesn't touch the DB, so tests call the route
function directly with a stub ``User`` — same style as
``test_roadmap_endpoint.py``.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from schemas.curriculum import CardCandidate
from routers.curriculum import get_card_candidates
from services.agent import card_cache


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    card_cache.clear()
    yield
    card_cache.clear()


def _user() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4())


def _card(front: str = "Q?", back: str = "A.") -> CardCandidate:
    return CardCandidate(front=front, back=back)


@pytest.mark.asyncio
async def test_returns_cached_cards_when_already_present() -> None:
    """Task completed before the endpoint is hit — immediate return."""
    sid, mid = uuid.uuid4(), uuid.uuid4()
    card_cache.put(sid, mid, [_card("Q1"), _card("Q2")])

    resp = await get_card_candidates(
        session_id=sid,
        message_id=mid,
        user=_user(),
    )

    assert resp.reason is None
    assert len(resp.cards) == 2
    assert [c.front for c in resp.cards] == ["Q1", "Q2"]


@pytest.mark.asyncio
async def test_returns_no_candidates_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No matching put ever fires → ``{cards:[], reason:'no_candidates'}``.

    We patch the endpoint's wait budget down from 10s to 0.1s so the
    test stays fast without needing a real 10-second wait.
    """
    sid, mid = uuid.uuid4(), uuid.uuid4()

    # Shrink the endpoint's wait window by patching ``await_or_get`` to
    # forward with a shorter timeout. Cleaner than poking module-private
    # constants — the endpoint passes ``timeout_s=10.0`` explicitly so
    # we intercept the call.
    real_await = card_cache.await_or_get

    async def _fast_await_or_get(sid_, mid_, timeout_s=10.0):
        return await real_await(sid_, mid_, timeout_s=0.1)

    monkeypatch.setattr(card_cache, "await_or_get", _fast_await_or_get)
    # The router imports the symbol at module load time, so rebind there
    # too for this test to see the patched version.
    from routers import curriculum as curriculum_router_module

    monkeypatch.setattr(
        curriculum_router_module.card_cache,
        "await_or_get",
        _fast_await_or_get,
    )

    resp = await get_card_candidates(
        session_id=sid,
        message_id=mid,
        user=_user(),
    )

    assert resp.reason == "no_candidates"
    assert resp.cards == []


@pytest.mark.asyncio
async def test_waits_for_inflight_put_within_budget() -> None:
    """``put`` lands during the endpoint's wait → endpoint returns cards."""
    sid, mid = uuid.uuid4(), uuid.uuid4()

    async def _delayed_put() -> None:
        await asyncio.sleep(0.05)
        card_cache.put(sid, mid, [_card("late"), _card("but-made-it")])

    # Launch both concurrently; the endpoint starts waiting before the
    # put arrives, then is woken by the event.
    producer = asyncio.create_task(_delayed_put())
    resp = await get_card_candidates(
        session_id=sid,
        message_id=mid,
        user=_user(),
    )
    await producer

    assert resp.reason is None
    assert [c.front for c in resp.cards] == ["late", "but-made-it"]


@pytest.mark.asyncio
async def test_empty_cards_returned_with_no_reason() -> None:
    """A completed task that produced zero cards is NOT ``no_candidates``.

    Important UX distinction: an explicit empty-result ``put`` means "we
    ran the spawner and it honestly had nothing to recall", while
    ``reason=no_candidates`` means "we gave up waiting". Frontend may
    choose to show different UI for these (probably just drops the
    toast for both, but the analytics differ).
    """
    sid, mid = uuid.uuid4(), uuid.uuid4()
    card_cache.put(sid, mid, [])

    resp = await get_card_candidates(
        session_id=sid,
        message_id=mid,
        user=_user(),
    )

    assert resp.cards == []
    assert resp.reason is None
