"""Tests for the LOOM (Learner-Oriented Ontology Memory) service."""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from services.loom_extraction import _BLOOM_LEVELS, extract_course_concepts
from services.loom_graph import (
    build_course_graph,
    check_prerequisite_gaps,
    generate_learning_path,
    get_mastery_graph,
    link_cross_course_concepts,
)
from services.loom_mastery import _bkt_update, update_concept_mastery

def _node(name, cid, nid=None, meta=None):
    n = MagicMock(); n.id = nid or uuid.uuid4(); n.course_id = cid; n.name = name
    n.description = ""; n.metadata_ = meta or {"bloom_level": 2, "bloom_label": "understand"}
    return n

def _edge(src, tgt, rel="prerequisite"):
    e = MagicMock(); e.id = uuid.uuid4(); e.source_id = src; e.target_id = tgt; e.relation_type = rel
    return e

def _mastery(uid, nid, score=0.0, pc=0, cc=0, wc=0, stab=0.0, lp=None, nr=None):
    m = MagicMock(); m.user_id = uid; m.knowledge_node_id = nid; m.mastery_score = score
    m.practice_count = pc; m.correct_count = cc; m.wrong_count = wc
    m.stability_days = stab; m.last_practiced_at = lp; m.next_review_at = nr
    return m

def _scalars(items):
    s = MagicMock(); s.all.return_value = items
    r = MagicMock(); r.scalars.return_value = s
    r.scalar_one_or_none.return_value = items[0] if items else None
    return r

def _scalar(v):
    r = MagicMock(); r.scalar.return_value = v; return r

def _fsrs_patch():
    return patch("services.spaced_repetition.fsrs.review_card")

def _fsrs_card(stability=1.0, due=None):
    c = MagicMock(); c.stability = stability
    c.due = due or datetime(2026, 3, 15, tzinfo=timezone.utc)
    return c

# ── BLOOM_LEVELS ──

def test_bloom_levels_complete():
    assert len(_BLOOM_LEVELS) == 6
    assert _BLOOM_LEVELS["remember"] == 1 and _BLOOM_LEVELS["create"] == 6

def test_bloom_levels_ordering():
    for i, lev in enumerate(["remember","understand","apply","analyze","evaluate","create"], 1):
        assert _BLOOM_LEVELS[lev] == i

# ── extract_course_concepts ──

@pytest.mark.asyncio
async def test_extract_skips_when_concepts_exist():
    db = AsyncMock(); cid = uuid.uuid4(); n = _node("Derivative", cid)
    db.execute = AsyncMock(side_effect=[_scalar(3), _scalars([n])])
    result = await extract_course_concepts(db, cid)
    assert len(result) == 1 and result[0].name == "Derivative"

@pytest.mark.asyncio
async def test_extract_returns_empty_when_no_content():
    db = AsyncMock(); cid = uuid.uuid4()
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([])])
    assert await extract_course_concepts(db, cid) == []

@pytest.mark.asyncio
async def test_extract_returns_empty_on_short_content():
    db = AsyncMock(); cid = uuid.uuid4()
    sn = MagicMock(); sn.content = "short"; sn.title = "Intro"
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([sn])])
    assert await extract_course_concepts(db, cid) == []

@pytest.mark.asyncio
async def test_extract_handles_malformed_json():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "Test"
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])
    mc = AsyncMock(); mc.extract = AsyncMock(return_value=("not json", {}))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        assert await extract_course_concepts(db, cid) == []

@pytest.mark.asyncio
async def test_extract_handles_no_json_array():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "Test"
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])
    mc = AsyncMock(); mc.extract = AsyncMock(return_value=('{"k":"v"}', {}))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        assert await extract_course_concepts(db, cid) == []

@pytest.mark.asyncio
async def test_extract_creates_nodes_and_edges():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "Calc"
    resp = ('[{"name":"Limit","description":"x","prerequisites":[],"related":[],"bloom_level":"understand"},'
            '{"name":"Derivative","description":"y","prerequisites":["Limit"],"related":[],"bloom_level":"apply"}]')
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])
    db.add = MagicMock(); db.flush = AsyncMock(); db.commit = AsyncMock()
    mc = AsyncMock(); mc.extract = AsyncMock(return_value=(resp, {}))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        result = await extract_course_concepts(db, cid)
    assert len(result) == 2 and {n.name for n in result} == {"Limit", "Derivative"}
    assert db.add.call_count >= 2

@pytest.mark.asyncio
async def test_extract_skips_empty_or_long_names():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "T"
    long_n = "X" * 201
    resp = (f'[{{"name":"","description":"e","prerequisites":[],"related":[],"bloom_level":"understand"}},'
            f'{{"name":"{long_n}","description":"l","prerequisites":[],"related":[],"bloom_level":"understand"}},'
            f'{{"name":"Valid","description":"ok","prerequisites":[],"related":[],"bloom_level":"understand"}}]')
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])
    db.add = MagicMock(); db.flush = AsyncMock(); db.commit = AsyncMock()
    mc = AsyncMock(); mc.extract = AsyncMock(return_value=(resp, {}))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        result = await extract_course_concepts(db, cid)
    assert len(result) == 1 and result[0].name == "Valid"

@pytest.mark.asyncio
async def test_extract_respects_max_nodes():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "Big"
    items = [f'{{"name":"C{i}","description":"c","prerequisites":[],"related":[],"bloom_level":"understand"}}' for i in range(20)]
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])
    db.add = MagicMock(); db.flush = AsyncMock(); db.commit = AsyncMock()
    mc = AsyncMock(); mc.extract = AsyncMock(return_value=("[" + ",".join(items) + "]", {}))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        assert len(await extract_course_concepts(db, cid, max_nodes=5)) == 5

@pytest.mark.asyncio
async def test_extract_handles_llm_connection_error():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "T"
    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])
    mc = AsyncMock(); mc.extract = AsyncMock(side_effect=ConnectionError("x"))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        assert await extract_course_concepts(db, cid) == []

# ── _bkt_update (BKT Bayesian mastery update) ──

def test_bkt_update_mcq_correct_low_mastery():
    """MCQ correct on low mastery: high guess rate means small increase."""
    result = _bkt_update(0.2, correct=True, question_type="mc")
    # With guess=0.25, correct barely moves low mastery
    assert result < 0.55  # Much less than free_response would give

def test_bkt_update_free_response_correct_low_mastery():
    """Free-response correct on low mastery: low guess rate means strong increase."""
    result = _bkt_update(0.2, correct=True, question_type="free_response")
    assert result > 0.5  # Strong evidence of learning

def test_bkt_update_mcq_vs_free_response():
    """MCQ correct should give less mastery than free_response correct."""
    mc = _bkt_update(0.3, correct=True, question_type="mc")
    fr = _bkt_update(0.3, correct=True, question_type="free_response")
    assert fr > mc

def test_bkt_update_incorrect_high_mastery():
    """Incorrect on high mastery: slip allows some tolerance."""
    result = _bkt_update(0.9, correct=False, question_type="mc")
    # Should decrease significantly
    assert result < 0.7

def test_bkt_update_tf_correct():
    """True/False: 50% guess rate means correct barely helps."""
    result = _bkt_update(0.3, correct=True, question_type="tf")
    assert result < 0.5  # High guess rate means weak evidence

def test_bkt_update_bounds():
    """BKT should always return values in [0, 1]."""
    assert 0.0 <= _bkt_update(0.0, True) <= 1.0
    assert 0.0 <= _bkt_update(1.0, False) <= 1.0
    assert 0.0 <= _bkt_update(0.5, True, "mc") <= 1.0

# ── update_concept_mastery ──

@pytest.mark.asyncio
async def test_update_mastery_missing_concept():
    db = AsyncMock(); db.execute = AsyncMock(return_value=_scalars([]))
    assert await update_concept_mastery(db, uuid.uuid4(), "X", uuid.uuid4(), True) is None

@pytest.mark.asyncio
async def test_update_mastery_correct_answer():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    n = _node("Derivative", cid)
    m = _mastery(uid, n.id, score=0.5, pc=3, cc=2, wc=1, stab=2.0)
    # Mock results: 1) find node, 2) find mastery,
    # 3) FIRe prereq edges, 4) consolidation parent edges, 5) sync LearningProgress
    no_progress = MagicMock(); no_progress.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[_scalars([n]), _scalars([m]), _scalars([]), _scalars([]), no_progress])
    db.flush = AsyncMock()
    with _fsrs_patch() as fp:
        fp.return_value = (_fsrs_card(5.0), MagicMock())
        r = await update_concept_mastery(db, uid, "Derivative", cid, correct=True)
    # BKT(0.5, correct, default guess=0.15, slip=0.10):
    # posterior = 0.5*0.9 / (0.5*0.9 + 0.5*0.15) = 0.857
    # updated = 0.857 + (1-0.857)*0.10 = 0.871
    assert r.mastery_score == pytest.approx(0.87, abs=0.02)
    assert r.practice_count == 4 and r.correct_count == 3

@pytest.mark.asyncio
async def test_update_mastery_incorrect_answer():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    n = _node("Integration", cid)
    m = _mastery(uid, n.id, score=0.8, pc=5, cc=4, wc=1, stab=3.0)
    # Mock results: 1) find node, 2) find mastery,
    # 3) FIRe prereq edges (now runs on incorrect too!), 4) consolidation parent edges, 5) sync LearningProgress
    no_progress = MagicMock(); no_progress.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[_scalars([n]), _scalars([m]), _scalars([]), _scalars([]), no_progress])
    db.flush = AsyncMock()
    with _fsrs_patch() as fp:
        fp.return_value = (_fsrs_card(1.0), MagicMock())
        r = await update_concept_mastery(db, uid, "Integration", cid, correct=False)
    # BKT(0.8, incorrect, default guess=0.15, slip=0.10):
    # posterior = 0.8*0.10 / (0.8*0.10 + 0.2*0.85) = 0.08/0.25 = 0.32
    # updated = 0.32 + 0.68*0.10 = 0.388
    assert r.mastery_score == pytest.approx(0.39, abs=0.02)
    assert r.wrong_count == 2

@pytest.mark.asyncio
async def test_update_mastery_creates_new_record():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    n = _node("Limit", cid)
    no_m = MagicMock(); no_m.scalar_one_or_none.return_value = None
    s = MagicMock(); s.all.return_value = []; no_m.scalars.return_value = s
    # Mock results: 1) find node, 2) no existing mastery,
    # 3) FIRe prereq edges, 4) consolidation parent edges, 5) sync LearningProgress
    no_progress = MagicMock(); no_progress.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[_scalars([n]), no_m, _scalars([]), _scalars([]), no_progress])
    added = []; db.add = lambda o: added.append(o); db.flush = AsyncMock()
    with _fsrs_patch() as fp:
        fp.return_value = (_fsrs_card(1.0), MagicMock())
        r = await update_concept_mastery(db, uid, "Limit", cid, correct=True)
    assert r is not None and len(added) == 1
    # BKT(0.0→0.001, correct, default): ~0.106
    assert r.mastery_score == pytest.approx(0.11, abs=0.02)
    assert r.practice_count == 1 and r.correct_count == 1

@pytest.mark.asyncio
async def test_update_mastery_bkt_from_zero():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    n = _node("Topic", cid)
    m = _mastery(uid, n.id, score=0.0, pc=0, cc=0, wc=0, stab=0.0)
    # Mock results: 1) find node, 2) find mastery,
    # 3) FIRe prereq edges, 4) consolidation parent edges, 5) sync LearningProgress
    no_progress = MagicMock(); no_progress.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[_scalars([n]), _scalars([m]), _scalars([]), _scalars([]), no_progress])
    db.flush = AsyncMock()
    with _fsrs_patch() as fp:
        fp.return_value = (_fsrs_card(1.0), MagicMock())
        r = await update_concept_mastery(db, uid, "Topic", cid, correct=True)
    # BKT(0.001, correct, default): ~0.106
    assert r.mastery_score == pytest.approx(0.11, abs=0.02)

@pytest.mark.asyncio
async def test_update_mastery_with_question_type():
    """Passing question_type should affect mastery via BKT guess/slip."""
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    n = _node("Concept", cid)
    m = _mastery(uid, n.id, score=0.3, pc=2, cc=1, wc=1, stab=1.0)
    no_progress = MagicMock(); no_progress.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(side_effect=[_scalars([n]), _scalars([m]), _scalars([]), _scalars([]), no_progress])
    db.flush = AsyncMock()
    with _fsrs_patch() as fp:
        fp.return_value = (_fsrs_card(2.0), MagicMock())
        r = await update_concept_mastery(db, uid, "Concept", cid, correct=True, question_type="mc")
    # MCQ correct with low prior should give less than default
    assert r.mastery_score < 0.7  # MCQ guess=0.25 means less credit

# ── get_mastery_graph ──

@pytest.mark.asyncio
async def test_mastery_graph_empty_course():
    db = AsyncMock(); db.execute = AsyncMock(return_value=_scalars([]))
    r = await get_mastery_graph(db, uuid.uuid4(), uuid.uuid4())
    assert r == {"nodes": [], "edges": [], "weak_concepts": [], "next_to_study": None}

@pytest.mark.asyncio
async def test_mastery_graph_with_nodes():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    n1, n2 = _node("Limit", cid), _node("Derivative", cid)
    e = _edge(n2.id, n1.id)
    m1 = _mastery(uid, n1.id, score=0.9, stab=0.0)
    m2 = _mastery(uid, n2.id, score=0.3, stab=0.0)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([n1, n2]), 2: _scalars([m1, m2]), 3: _scalars([e]),
                4: _scalars([n1, n2]), 5: _scalars([m2])}.get(cc, _scalars([e]))
    db.execute = exe
    r = await get_mastery_graph(db, uid, cid)
    assert len(r["nodes"]) == 2 and len(r["edges"]) == 1
    assert "Derivative" in r["weak_concepts"]

# ── check_prerequisite_gaps ──

@pytest.mark.asyncio
async def test_prerequisite_gaps_empty_course():
    db = AsyncMock(); db.execute = AsyncMock(return_value=_scalars([]))
    assert await check_prerequisite_gaps(db, uuid.uuid4(), uuid.uuid4()) == []

@pytest.mark.asyncio
async def test_prerequisite_gaps_finds_weak_prereqs():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    pr, fl = _node("Algebra", cid), _node("Calculus", cid)
    e = _edge(fl.id, pr.id)
    mp, mf = _mastery(uid, pr.id, score=0.2), _mastery(uid, fl.id, score=0.3)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([pr, fl]), 2: _scalars([e]), 3: _scalars([mp, mf])}.get(cc, _scalars([]))
    db.execute = exe
    r = await check_prerequisite_gaps(db, uid, cid, failed_concept_names=["Calculus"])
    assert len(r) == 1 and r[0]["concept"] == "Algebra"
    assert r[0]["mastery"] == 0.2 and r[0]["gap_severity"] == 0.8

@pytest.mark.asyncio
async def test_prerequisite_gaps_above_threshold():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    pr, fl = _node("Algebra", cid), _node("Calculus", cid)
    mp = _mastery(uid, pr.id, score=0.5); mf = _mastery(uid, fl.id, score=0.3)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([pr, fl]), 2: _scalars([]), 3: _scalars([mp, mf])}.get(cc, _scalars([]))
    db.execute = exe
    r = await check_prerequisite_gaps(db, uid, cid, failed_concept_names=["Calculus"], mastery_threshold=0.4)
    assert len(r) == 0

# ── generate_learning_path ──

@pytest.mark.asyncio
async def test_learning_path_empty_course():
    db = AsyncMock(); db.execute = AsyncMock(return_value=_scalars([]))
    assert await generate_learning_path(db, uuid.uuid4(), uuid.uuid4()) == []

@pytest.mark.asyncio
async def test_learning_path_all_mastered():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    n = _node("Easy", cid); m = _mastery(uid, n.id, score=0.9)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([n]), 2: _scalars([m])}.get(cc, _scalars([]))
    db.execute = exe
    assert await generate_learning_path(db, cid, uid) == []

@pytest.mark.asyncio
async def test_learning_path_respects_prerequisite_order():
    db = AsyncMock(); uid, cid = uuid.uuid4(), uuid.uuid4()
    np = _node("Algebra", cid, meta={"bloom_level": 1})
    nd = _node("Calculus", cid, meta={"bloom_level": 3})
    e = _edge(nd.id, np.id)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([np, nd]), 2: _scalars([]), 3: _scalars([e])}.get(cc, _scalars([]))
    db.execute = exe
    r = await generate_learning_path(db, cid, uid)
    names = [x["name"] for x in r]
    assert names.index("Algebra") < names.index("Calculus")

# ── link_cross_course_concepts ──

@pytest.mark.asyncio
async def test_cross_course_no_nodes():
    db = AsyncMock(); db.execute = AsyncMock(return_value=_scalars([]))
    assert await link_cross_course_concepts(db, uuid.uuid4()) == 0

@pytest.mark.asyncio
async def test_cross_course_no_matches():
    db = AsyncMock(); cid, ocid = uuid.uuid4(), uuid.uuid4()
    na, nb = _node("Quantum", cid), _node("History", ocid)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([na]), 2: _scalars([nb])}.get(cc, _scalars([]))
    db.execute = exe
    assert await link_cross_course_concepts(db, cid) == 0

@pytest.mark.asyncio
async def test_cross_course_links_matching_concepts():
    db = AsyncMock(); cid, ocid = uuid.uuid4(), uuid.uuid4()
    na, nb = _node("Eigenvalue", cid), _node("eigenvalue", ocid)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([na]), 2: _scalars([nb]), 3: _scalars([])}.get(cc, _scalars([]))
    db.execute = exe; db.add = MagicMock(); db.flush = AsyncMock()
    assert await link_cross_course_concepts(db, cid) == 1
    assert db.add.call_count == 2

@pytest.mark.asyncio
async def test_cross_course_no_other_courses():
    db = AsyncMock(); cid = uuid.uuid4(); na = _node("Algebra", cid)
    cc = 0
    async def exe(stmt):
        nonlocal cc; cc += 1
        return {1: _scalars([na]), 2: _scalars([])}.get(cc, _scalars([]))
    db.execute = exe
    assert await link_cross_course_concepts(db, cid) == 0

# ── build_course_graph ──

@pytest.mark.asyncio
async def test_build_course_graph_success():
    cid = uuid.uuid4(); mdb = AsyncMock()
    ctx = AsyncMock(); ctx.__aenter__ = AsyncMock(return_value=mdb); ctx.__aexit__ = AsyncMock(return_value=False)
    with (patch("services.loom_extraction.extract_course_concepts", new_callable=AsyncMock) as me,
          patch("services.loom_graph.link_cross_course_concepts", new_callable=AsyncMock) as ml,
          patch("services.loom_confusion.compute_interference_matrix", new_callable=AsyncMock) as mi):
        me.return_value = [_node("A", cid), _node("B", cid)]; ml.return_value = 0; mi.return_value = []
        assert await build_course_graph(lambda: ctx, cid) == 2

@pytest.mark.asyncio
async def test_build_course_graph_handles_exception():
    def factory(): raise RuntimeError("DB down")
    assert await build_course_graph(factory, uuid.uuid4()) == 0
