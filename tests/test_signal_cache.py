"""collect_signals: sequential on one session, cached per chat session."""

import uuid
from unittest.mock import AsyncMock

import pytest

from services.agent import signals as signals_pkg
from services.agent.signals import AgendaSignal, clear_signal_cache, collect_signals


def _sig(user_id, name):
    return AgendaSignal(signal_type="weak_area", user_id=user_id, course_id=None, entity_id=name, title=name, urgency=1.0)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_signal_cache()
    yield
    clear_signal_cache()


@pytest.mark.asyncio
async def test_collectors_run_sequentially_on_the_shared_session(monkeypatch):
    user_id = uuid.uuid4()
    active = {"count": 0, "max": 0}

    async def collector(uid, cid, db):
        active["count"] += 1
        active["max"] = max(active["max"], active["count"])
        try:
            return [_sig(uid, "x")]
        finally:
            active["count"] -= 1

    monkeypatch.setattr(signals_pkg, "_COLLECTORS", [collector, collector, collector])
    result = await collect_signals(user_id, None, db=AsyncMock())
    assert len(result) == 3
    assert active["max"] == 1


@pytest.mark.asyncio
async def test_cache_key_reuses_result_within_ttl(monkeypatch):
    user_id = uuid.uuid4()
    calls = {"n": 0}

    async def collector(uid, cid, db):
        calls["n"] += 1
        return [_sig(uid, f"run{calls['n']}")]

    monkeypatch.setattr(signals_pkg, "_COLLECTORS", [collector])
    first = await collect_signals(user_id, None, db=AsyncMock(), cache_key="session-1")
    second = await collect_signals(user_id, None, db=AsyncMock(), cache_key="session-1")
    assert calls["n"] == 1
    assert [s.entity_id for s in first] == [s.entity_id for s in second] == ["run1"]

    # No cache key → fresh collection (agenda tick path)
    await collect_signals(user_id, None, db=AsyncMock())
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(monkeypatch):
    user_id = uuid.uuid4()
    calls = {"n": 0}

    async def collector(uid, cid, db):
        calls["n"] += 1
        return []

    monkeypatch.setattr(signals_pkg, "_COLLECTORS", [collector])
    clock = {"t": 1000.0}
    monkeypatch.setattr(signals_pkg.time, "monotonic", lambda: clock["t"])

    await collect_signals(user_id, None, db=AsyncMock(), cache_key="s")
    clock["t"] += signals_pkg.SIGNAL_CACHE_TTL_SECONDS + 1
    await collect_signals(user_id, None, db=AsyncMock(), cache_key="s")
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_cache_is_bounded(monkeypatch):
    user_id = uuid.uuid4()

    async def collector(uid, cid, db):
        return []

    monkeypatch.setattr(signals_pkg, "_COLLECTORS", [collector])
    monkeypatch.setattr(signals_pkg, "SIGNAL_CACHE_MAX_ENTRIES", 5)
    for i in range(20):
        await collect_signals(user_id, None, db=AsyncMock(), cache_key=f"s{i}")
    assert len(signals_pkg._signal_cache) == 5
    assert "s19" in signals_pkg._signal_cache and "s0" not in signals_pkg._signal_cache
