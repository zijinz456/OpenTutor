"""Tests for LECTOR -- LLM-Enhanced Concept-aware Tutoring and Optimized Review.

Covers: smart review session generation, priority scoring (low mastery, never practiced,
time decay, prerequisites, confusion pairs, FSRS overdue), review summary, review outcome
recording, session structuring (warm-up, interleaving, contrast, peak-end), analytics.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.lector import (
    ReviewItem, get_smart_review_session, get_review_summary, record_review_outcome,
)
from services.lector_session import (
    build_structured_session, _interleave_by_group, _build_contrast_pairs,
)
try:
    from services.lector_analytics import (
        compute_review_effectiveness, get_review_effectiveness_for_api,
    )
except ImportError:
    compute_review_effectiveness = None
    get_review_effectiveness_for_api = None

_uid = uuid.uuid4

# Default LECTOR settings applied via mock
_LECTOR_DEFAULTS = dict(
    lector_mastery_threshold=0.8, lector_factor_low_mastery=0.5,
    lector_factor_never_practiced=0.3, lector_factor_time_decay=0.3,
    lector_factor_prerequisite=0.2, lector_factor_confusion=0.1,
    lector_prerequisite_threshold=0.5, lector_confusion_threshold=0.6,
    lector_factor_interference=0.15,
)


def _node(cid, name="C"):
    return SimpleNamespace(id=_uid(), course_id=cid, name=name, metadata_={}, description=None)


def _edge(src, tgt, rel="related"):
    return SimpleNamespace(id=_uid(), source_id=src, target_id=tgt, relation_type=rel, weight=1.0)


def _mastery(uid, nid, score=0.5, pcount=1, stab=5.0, last=None, nxt=None, cc=0, wc=0):
    return SimpleNamespace(
        id=_uid(), user_id=uid, knowledge_node_id=nid, mastery_score=score,
        practice_count=pcount, stability_days=stab, last_practiced_at=last,
        next_review_at=nxt, correct_count=cc, wrong_count=wc,
    )


def _item(name="C", mastery=0.5, priority=0.5, reason="test", related=None, rtype="standard"):
    return ReviewItem(
        concept_name=name, concept_id=str(_uid()), mastery=mastery,
        priority=priority, reason=reason, related_concepts=related or [], review_type=rtype,
    )


def _mock_db(sequences):
    """Create AsyncMock db whose .execute returns results in order."""
    results = []
    for items in sequences:
        m = MagicMock()
        s = MagicMock(); s.all.return_value = items
        m.scalars.return_value = s
        m.scalar_one_or_none.return_value = items[0] if items else None
        m.all.return_value = [(i.id,) for i in items] if items else []
        results.append(m)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=results)
    db.flush = AsyncMock()
    return db


def _settings_mock():
    p = patch("services.lector.settings")
    m = p.start()
    for k, v in _LECTOR_DEFAULTS.items():
        setattr(m, k, v)
    return p, m


# ── get_smart_review_session ──

@pytest.mark.asyncio
async def test_review_empty_course():
    db = _mock_db([[]])
    assert await get_smart_review_session(db, _uid(), _uid()) == []


@pytest.mark.asyncio
async def test_review_never_practiced():
    cid, uid = _uid(), _uid()
    n = _node(cid, "Derivatives")
    db = _mock_db([[n], [], []])
    p, _ = _settings_mock()
    try:
        r = await get_smart_review_session(db, uid, cid)
        assert len(r) == 1 and "not yet practiced" in r[0].reason
    finally:
        p.stop()


@pytest.mark.asyncio
async def test_review_low_mastery():
    cid, uid = _uid(), _uid()
    n = _node(cid, "Integrals")
    m = _mastery(uid, n.id, score=0.2, pcount=3)
    db = _mock_db([[n], [m], []])
    p, _ = _settings_mock()
    try:
        r = await get_smart_review_session(db, uid, cid)
        assert len(r) == 1 and "low mastery" in r[0].reason
    finally:
        p.stop()


@pytest.mark.asyncio
async def test_review_prerequisite_weak():
    cid, uid = _uid(), _uid()
    prereq, main = _node(cid, "Algebra"), _node(cid, "Calculus")
    edge = _edge(main.id, prereq.id, "prerequisite")
    pm = _mastery(uid, prereq.id, score=0.3, pcount=2)
    mm = _mastery(uid, main.id, score=0.4, pcount=1)
    db = _mock_db([[prereq, main], [pm, mm], [edge]])
    p, _ = _settings_mock()
    try:
        r = await get_smart_review_session(db, uid, cid)
        calc = next(i for i in r if i.concept_name == "Calculus")
        assert calc.review_type == "prerequisite_first" and "prerequisite" in calc.reason
    finally:
        p.stop()


@pytest.mark.asyncio
async def test_review_confusion_pair():
    cid, uid = _uid(), _uid()
    a, b = _node(cid, "Mean"), _node(cid, "Median")
    edge = _edge(a.id, b.id, "confused_with")
    ma, mb = _mastery(uid, a.id, score=0.4, pcount=2), _mastery(uid, b.id, score=0.4, pcount=2)
    db = _mock_db([[a, b], [ma, mb], [edge]])
    p, _ = _settings_mock()
    try:
        r = await get_smart_review_session(db, uid, cid)
        mean = next(i for i in r if i.concept_name == "Mean")
        assert mean.review_type == "contrast"
    finally:
        p.stop()


@pytest.mark.asyncio
async def test_review_time_decay():
    cid, uid = _uid(), _uid()
    n = _node(cid, "Limits")
    now = datetime.now(timezone.utc)
    m = _mastery(uid, n.id, score=0.7, pcount=5, stab=3.0, last=now - timedelta(days=10))
    db = _mock_db([[n], [m], []])
    p, _ = _settings_mock()
    try:
        r = await get_smart_review_session(db, uid, cid)
        assert len(r) == 1 and "memory decaying" in r[0].reason
    finally:
        p.stop()


@pytest.mark.asyncio
async def test_review_well_mastered_skipped():
    cid, uid = _uid(), _uid()
    n = _node(cid, "Addition")
    now = datetime.now(timezone.utc)
    m = _mastery(uid, n.id, score=0.95, pcount=20, stab=30.0, last=now - timedelta(days=1))
    db = _mock_db([[n], [m], []])
    p, _ = _settings_mock()
    try:
        assert await get_smart_review_session(db, uid, cid) == []
    finally:
        p.stop()


@pytest.mark.asyncio
async def test_review_max_items_and_sort():
    cid, uid = _uid(), _uid()
    nodes = [_node(cid, f"C{i}") for i in range(15)]
    db = _mock_db([nodes, [], []])
    p, _ = _settings_mock()
    try:
        r = await get_smart_review_session(db, uid, cid, max_items=5)
        assert len(r) <= 5
        assert [i.priority for i in r] == sorted([i.priority for i in r], reverse=True)
    finally:
        p.stop()


# ── get_review_summary ──

@pytest.mark.asyncio
async def test_summary_empty():
    with patch("services.lector.get_smart_review_session", new_callable=AsyncMock, return_value=[]):
        s = await get_review_summary(AsyncMock(), _uid(), _uid())
    assert s["needs_review"] is False and "All caught up" in s["recommendation"]


@pytest.mark.asyncio
async def test_summary_urgent():
    items = [_item("A", priority=0.8), _item("B", priority=0.7), _item("C", priority=0.6)]
    with patch("services.lector.get_smart_review_session", new_callable=AsyncMock, return_value=items):
        s = await get_review_summary(AsyncMock(), _uid(), _uid())
    assert s["urgent_count"] == 3 and s["needs_review"] is True


@pytest.mark.asyncio
async def test_summary_low_priority():
    with patch("services.lector.get_smart_review_session", new_callable=AsyncMock,
               return_value=[_item("X", priority=0.3)]):
        s = await get_review_summary(AsyncMock(), _uid(), _uid())
    assert s["urgent_count"] == 0 and "Consider reviewing" in s["recommendation"]


# ── record_review_outcome ──

@pytest.mark.asyncio
async def test_outcome_correct():
    uid, cid = _uid(), _uid()
    past = datetime.now(timezone.utc) - timedelta(days=5)
    m = _mastery(uid, cid, score=0.5, pcount=3, stab=5.0, cc=2, wc=1, last=past)
    n = _node(_uid(), "T")
    db = _mock_db([[m], [n]])
    await record_review_outcome(db, uid, cid, recalled_correctly=True)
    assert m.practice_count == 4 and m.correct_count == 3
    assert m.mastery_score > 0.5 and m.stability_days > 5.0
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_outcome_incorrect():
    uid, cid = _uid(), _uid()
    past = datetime.now(timezone.utc) - timedelta(days=5)
    m = _mastery(uid, cid, score=0.6, pcount=5, stab=10.0, cc=4, wc=1, last=past)
    db = _mock_db([[m], [_node(_uid(), "T")]])
    await record_review_outcome(db, uid, cid, recalled_correctly=False)
    assert m.wrong_count == 2 and m.mastery_score == pytest.approx(0.5, abs=0.01)
    assert m.stability_days < 10.0


@pytest.mark.asyncio
async def test_outcome_missing_mastery():
    rm = MagicMock(); rm.scalar_one_or_none.return_value = None
    db = AsyncMock(); db.execute = AsyncMock(return_value=rm); db.flush = AsyncMock()
    await record_review_outcome(db, _uid(), _uid(), recalled_correctly=True)
    db.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_outcome_bounds():
    uid, cid = _uid(), _uid()
    mh = _mastery(uid, cid, score=0.99, pcount=10, stab=5.0, cc=9, wc=1)
    db = _mock_db([[mh], [_node(_uid(), "T")]])
    await record_review_outcome(db, uid, cid, recalled_correctly=True)
    assert mh.mastery_score <= 1.0
    ml = _mastery(uid, cid, score=0.05, pcount=10, stab=1.0, cc=1, wc=9)
    db2 = _mock_db([[ml], [_node(_uid(), "T")]])
    await record_review_outcome(db2, uid, cid, recalled_correctly=False)
    assert ml.mastery_score >= 0.0


# ── build_structured_session ──

@pytest.mark.asyncio
async def test_session_empty():
    assert await build_structured_session([]) == []


@pytest.mark.asyncio
async def test_session_warm_up_first():
    items = [_item("Hard", mastery=0.2, priority=0.9), _item("Easy", mastery=0.7, priority=0.3)]
    r = await build_structured_session(items)
    assert r[0].concept_name == "Easy"


@pytest.mark.asyncio
async def test_session_peak_end():
    items = [_item("W", mastery=0.7, priority=0.3), _item("P", mastery=0.2, priority=0.9),
             _item("M", mastery=0.3, priority=0.5)]
    r = await build_structured_session(items)
    assert r[-1].concept_name == "P"


@pytest.mark.asyncio
async def test_session_contrast_adjacent():
    items = [_item("X", mastery=0.3, priority=0.6, rtype="contrast", related=["g"]),
             _item("Y", mastery=0.3, priority=0.5, rtype="contrast", related=["g"]),
             _item("Z", mastery=0.6, priority=0.4)]
    r = await build_structured_session(items)
    ci = [i for i, x in enumerate(r) if x.review_type == "contrast"]
    if len(ci) == 2:
        assert abs(ci[1] - ci[0]) == 1


@pytest.mark.asyncio
async def test_session_max_items():
    items = [_item(f"C{i}", priority=0.5 + i * 0.01) for i in range(20)]
    assert len(await build_structured_session(items, max_items=5)) <= 5


# ── _interleave_by_group / _build_contrast_pairs ──

def test_interleave_empty_and_single():
    assert _interleave_by_group([]) == []
    i = _item("A")
    assert _interleave_by_group([i]) == [i]


def test_interleave_alternates_groups():
    items = [_item("A1", related=["G1"]), _item("A2", related=["G1"]),
             _item("B1", related=["G2"]), _item("B2", related=["G2"])]
    r = _interleave_by_group(items)
    assert r[0].related_concepts[0] != r[1].related_concepts[0]


def test_contrast_pairs_cluster():
    items = [_item("C", related=["Z"]), _item("A", related=["X"]), _item("B", related=["X"])]
    r = _build_contrast_pairs(items)
    assert r[0].concept_name in ("A", "B") and r[1].concept_name in ("A", "B")


# ── Analytics ──

_skip_analytics = pytest.mark.skipif(
    compute_review_effectiveness is None,
    reason="services.lector_analytics removed",
)


@_skip_analytics
@pytest.mark.asyncio
async def test_analytics_empty():
    rm = MagicMock(); rm.all.return_value = []
    db = AsyncMock(); db.execute = AsyncMock(return_value=rm)
    m = await compute_review_effectiveness(db, _uid(), _uid())
    assert m["total_concepts"] == 0 and m["avg_mastery"] == 0.0


@_skip_analytics
@pytest.mark.asyncio
async def test_analytics_with_data():
    uid, now = _uid(), datetime.now(timezone.utc)
    nids = [_uid(), _uid(), _uid()]
    masteries = [
        _mastery(uid, nids[0], score=0.8, pcount=5, stab=10.0, nxt=now + timedelta(days=5)),
        _mastery(uid, nids[1], score=0.3, pcount=2, stab=3.0, nxt=now - timedelta(days=1)),
        _mastery(uid, nids[2], score=0.0, pcount=0, stab=0.0),
    ]
    nr = MagicMock(); nr.all.return_value = [(n,) for n in nids]
    mr = MagicMock(); s = MagicMock(); s.all.return_value = masteries; mr.scalars.return_value = s
    db = AsyncMock(); db.execute = AsyncMock(side_effect=[nr, mr])
    m = await compute_review_effectiveness(db, uid, _uid())
    assert m["total_concepts"] == 3 and m["reviewed_concepts"] == 2
    assert m["avg_mastery"] == pytest.approx(1.1 / 3, abs=0.01) and m["overdue_count"] == 1


@_skip_analytics
@pytest.mark.asyncio
async def test_api_effectiveness_derived():
    base = dict(total_concepts=10, reviewed_concepts=5, avg_mastery=0.6,
                overdue_count=1, avg_stability_days=7.0)
    with patch("services.lector_analytics.compute_review_effectiveness",
               new_callable=AsyncMock, return_value=base):
        r = await get_review_effectiveness_for_api(AsyncMock(), _uid(), _uid())
    assert r["coverage_pct"] == 50.0 and 0 <= r["health_score"] <= 100


@_skip_analytics
@pytest.mark.asyncio
async def test_api_effectiveness_zero_division():
    for total, rev in [(5, 0), (0, 0)]:
        base = dict(total_concepts=total, reviewed_concepts=rev, avg_mastery=0.0,
                    overdue_count=0, avg_stability_days=0.0)
        with patch("services.lector_analytics.compute_review_effectiveness",
                   new_callable=AsyncMock, return_value=base):
            r = await get_review_effectiveness_for_api(AsyncMock(), _uid(), _uid())
        assert r["coverage_pct"] == 0.0 and r["health_score"] >= 0
