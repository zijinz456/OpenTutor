"""Cache eviction tests for the cognitive-load in-memory caches (issue #30).

Both caches already enforce a hard bound in code; these tests pin that
behavior so a regression back to unbounded growth fails loudly:

- ``cognitive_load_nlp._analysis_cache`` — capped at 500, evicts the oldest
  half when full
- ``cognitive_load_calibrator._cache`` — capped at 200, evicts the
  least-active (lowest ``message_count``) baseline
"""

import uuid
from unittest.mock import patch

import pytest

from services import cognitive_load_nlp as nlp
from services import cognitive_load_calibrator as calibrator
from services.cognitive_load_nlp import analyze_student_affect
from services.cognitive_load_calibrator import StudentBaseline, get_or_create_baseline


@pytest.fixture(autouse=True)
def _clean_caches(monkeypatch):
    # Shrink the caps so eviction triggers in a handful of calls — the
    # eviction logic reads the module attribute at call time, so behavior
    # is identical to the production 500/200 values.
    monkeypatch.setattr(nlp, "_MAX_CACHE_SIZE", 10)
    monkeypatch.setattr(calibrator, "_MAX_CACHE_SIZE", 10)
    nlp._analysis_cache.clear()
    calibrator._cache.clear()
    yield
    nlp._analysis_cache.clear()
    calibrator._cache.clear()


def _llm_unavailable():
    """Force analyze_student_affect down the deterministic keyword fallback."""
    return patch(
        "services.llm.router.get_llm_client",
        side_effect=RuntimeError("no llm in test"),
    )


# ── NLP analysis cache ──


@pytest.mark.asyncio
async def test_nlp_cache_never_exceeds_max_size():
    with _llm_unavailable():
        for i in range(nlp._MAX_CACHE_SIZE + 40):
            await analyze_student_affect(f"unique message number {i}")

    assert len(nlp._analysis_cache) <= nlp._MAX_CACHE_SIZE


@pytest.mark.asyncio
async def test_nlp_cache_eviction_drops_oldest_keeps_newest():
    with _llm_unavailable():
        for i in range(nlp._MAX_CACHE_SIZE + 1):
            await analyze_student_affect(f"unique message number {i}")

    # Crossing the cap flushes the oldest half; the newest entry must survive
    assert f"unique message number {nlp._MAX_CACHE_SIZE}"[:200] in nlp._analysis_cache
    assert "unique message number 0"[:200] not in nlp._analysis_cache
    assert len(nlp._analysis_cache) <= nlp._MAX_CACHE_SIZE


@pytest.mark.asyncio
async def test_nlp_cache_hit_skips_reanalysis():
    with _llm_unavailable():
        first = await analyze_student_affect("same message")
    # No LLM patch on the second call: a cache hit must return before any
    # LLM/fallback work happens, so the result object is identical
    second = await analyze_student_affect("same message")
    assert second is first
    assert len(nlp._analysis_cache) == 1


# ── Calibrator baseline cache ──


def test_calibrator_cache_never_exceeds_max_size():
    for _ in range(calibrator._MAX_CACHE_SIZE + 50):
        get_or_create_baseline(uuid.uuid4())

    assert len(calibrator._cache) <= calibrator._MAX_CACHE_SIZE


def test_calibrator_evicts_least_active_baseline():
    # Fill the cache; give everyone some activity except one idle user
    idle_user = uuid.uuid4()
    get_or_create_baseline(idle_user).message_count = 0
    active_ids = [uuid.uuid4() for _ in range(calibrator._MAX_CACHE_SIZE - 1)]
    for uid in active_ids:
        get_or_create_baseline(uid).message_count = 10

    assert len(calibrator._cache) == calibrator._MAX_CACHE_SIZE

    # One more user forces eviction of the least-active baseline
    newcomer = uuid.uuid4()
    get_or_create_baseline(newcomer)

    assert str(idle_user) not in calibrator._cache
    assert str(newcomer) in calibrator._cache
    assert len(calibrator._cache) == calibrator._MAX_CACHE_SIZE


def test_calibrator_returns_same_instance_for_same_user():
    uid = uuid.uuid4()
    a = get_or_create_baseline(uid)
    b = get_or_create_baseline(uid)
    assert a is b
    assert isinstance(a, StudentBaseline)
