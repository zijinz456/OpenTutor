"""Tests for LOOM knowledge graph DAG validation (cycle detection + repair)."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.knowledge_graph import KnowledgeNode
from services.loom_extraction import extract_course_concepts
from services.loom_graph import (
    _find_cycle,
    resolve_prerequisite_cycles,
    validate_graph,
)


def _ids(n):
    return [uuid.uuid4() for _ in range(n)]


def _edge(src, tgt, weight=1.0):
    e = MagicMock()
    e.source_id = src
    e.target_id = tgt
    e.relation_type = "prerequisite"
    e.weight = weight
    return e


def _node(name, nid):
    n = MagicMock()
    n.id = nid
    n.name = name
    return n


def _scalars(items):
    s = MagicMock(); s.all.return_value = items
    r = MagicMock(); r.scalars.return_value = s
    return r


# ── _find_cycle ──

def test_find_cycle_returns_none_for_dag():
    a, b, c = _ids(3)
    assert _find_cycle({a, b, c}, [(a, b), (b, c)]) is None


def test_find_cycle_returns_none_for_empty_graph():
    assert _find_cycle(set(), []) is None


def test_find_cycle_detects_triangle():
    a, b, c = _ids(3)
    cycle = _find_cycle({a, b, c}, [(a, b), (b, c), (c, a)])
    assert cycle is not None
    assert set(cycle) == {a, b, c}
    # Cycle is returned in edge order: each consecutive pair is a real edge
    pairs = set(zip(cycle, cycle[1:] + cycle[:1]))
    assert pairs <= {(a, b), (b, c), (c, a)}


def test_find_cycle_detects_self_loop():
    a, b = _ids(2)
    cycle = _find_cycle({a, b}, [(a, a), (a, b)])
    assert cycle == [a]


def test_find_cycle_ignores_acyclic_tail():
    # Triangle a->b->c->a plus a tail c->d: d is downstream of the cycle and
    # never peels, but the extracted cycle must not include it.
    a, b, c, d = _ids(4)
    cycle = _find_cycle({a, b, c, d}, [(a, b), (b, c), (c, a), (c, d)])
    assert cycle is not None
    assert set(cycle) == {a, b, c}


def test_find_cycle_ignores_edges_outside_node_set():
    a, b = _ids(2)
    ghost = uuid.uuid4()
    assert _find_cycle({a, b}, [(a, b), (b, ghost), (ghost, a)]) is None


# ── resolve_prerequisite_cycles ──

def test_resolve_returns_empty_for_dag():
    a, b, c = _ids(3)
    edges = [_edge(a, b), _edge(b, c)]
    cycles, to_remove = resolve_prerequisite_cycles({a, b, c}, edges)
    assert cycles == [] and to_remove == []


def test_resolve_breaks_weakest_link():
    a, b, c = _ids(3)
    weak = _edge(b, c, weight=0.3)
    edges = [_edge(a, b, weight=1.0), weak, _edge(c, a, weight=0.9)]
    cycles, to_remove = resolve_prerequisite_cycles({a, b, c}, edges)
    assert len(cycles) == 1 and set(cycles[0]) == {a, b, c}
    assert to_remove == [weak]


def test_resolve_treats_none_weight_as_default():
    # Pending (unflushed) edges have weight=None; the column default is 1.0,
    # so an explicit lower weight must lose to a None weight.
    a, b = _ids(2)
    weak = _edge(a, b, weight=0.5)
    pending = _edge(b, a, weight=None)
    cycles, to_remove = resolve_prerequisite_cycles({a, b}, [pending, weak])
    assert len(cycles) == 1
    assert to_remove == [weak]


def test_resolve_breaks_multiple_independent_cycles():
    a, b, c, d = _ids(4)
    weak1 = _edge(b, a, weight=0.1)
    weak2 = _edge(d, c, weight=0.2)
    edges = [_edge(a, b), weak1, _edge(c, d), weak2]
    cycles, to_remove = resolve_prerequisite_cycles({a, b, c, d}, edges)
    assert len(cycles) == 2
    assert set(to_remove) == {weak1, weak2}


def test_resolve_does_not_mutate_input():
    a, b = _ids(2)
    edges = [_edge(a, b), _edge(b, a)]
    resolve_prerequisite_cycles({a, b}, edges)
    assert len(edges) == 2


# ── validate_graph ──

@pytest.mark.asyncio
async def test_validate_graph_empty_course_is_dag():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalars([])])
    result = await validate_graph(db, uuid.uuid4())
    assert result == {"is_dag": True, "cycles": [], "removed_edges": []}


@pytest.mark.asyncio
async def test_validate_graph_acyclic():
    aid, bid = _ids(2)
    nodes = [_node("Limit", aid), _node("Derivative", bid)]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalars(nodes), _scalars([_edge(bid, aid)])])
    result = await validate_graph(db, uuid.uuid4())
    assert result["is_dag"] is True
    assert result["cycles"] == [] and result["removed_edges"] == []


@pytest.mark.asyncio
async def test_validate_graph_detects_cycle_without_repair():
    aid, bid, cid_ = _ids(3)
    nodes = [_node("A", aid), _node("B", bid), _node("C", cid_)]
    edges = [_edge(aid, bid), _edge(bid, cid_), _edge(cid_, aid, weight=0.2)]
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalars(nodes), _scalars(edges)])
    db.delete = AsyncMock(); db.flush = AsyncMock()
    result = await validate_graph(db, uuid.uuid4())
    assert result["is_dag"] is False
    assert sorted(result["cycles"][0]) == ["A", "B", "C"]
    assert result["removed_edges"] == [{"source": "C", "target": "A", "weight": 0.2}]
    db.delete.assert_not_called()


@pytest.mark.asyncio
async def test_validate_graph_repair_deletes_weakest_edge():
    aid, bid = _ids(2)
    nodes = [_node("A", aid), _node("B", bid)]
    weak = _edge(bid, aid, weight=0.4)
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_scalars(nodes), _scalars([_edge(aid, bid), weak])])
    db.delete = AsyncMock(); db.flush = AsyncMock()
    result = await validate_graph(db, uuid.uuid4(), repair=True)
    assert result["is_dag"] is False
    db.delete.assert_awaited_once_with(weak)
    db.flush.assert_awaited()


# ── extraction integration: cycles broken before commit ──

@pytest.mark.asyncio
async def test_extract_breaks_circular_prerequisites():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "Calc"
    resp = ('[{"name":"Limit","description":"x","prerequisites":["Derivative"],"related":[],"bloom_level":"understand"},'
            '{"name":"Derivative","description":"y","prerequisites":["Limit"],"related":[],"bloom_level":"apply"}]')

    def _scalar(v):
        r = MagicMock(); r.scalar.return_value = v; return r

    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])

    # Real KnowledgeNode ids are only assigned at flush; the mocked flush
    # never runs the ORM, so assign ids at add-time to let edges be created.
    def _assign_id(obj):
        if isinstance(obj, KnowledgeNode) and obj.id is None:
            obj.id = uuid.uuid4()

    db.add = MagicMock(side_effect=_assign_id)
    db.expunge = MagicMock()
    db.flush = AsyncMock(); db.commit = AsyncMock()
    mc = AsyncMock(); mc.extract = AsyncMock(return_value=(resp, {}))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        result = await extract_course_concepts(db, cid)

    assert len(result) == 2
    # The two-node cycle (Limit <-> Derivative) must be broken by dropping one edge
    assert db.expunge.call_count == 1
    dropped = db.expunge.call_args[0][0]
    assert dropped.relation_type == "prerequisite"


@pytest.mark.asyncio
async def test_extract_keeps_acyclic_prerequisites():
    db = AsyncMock(); cid = uuid.uuid4()
    cn = MagicMock(); cn.content = "A" * 300; cn.title = "Calc"
    resp = ('[{"name":"Limit","description":"x","prerequisites":[],"related":[],"bloom_level":"understand"},'
            '{"name":"Derivative","description":"y","prerequisites":["Limit"],"related":[],"bloom_level":"apply"}]')

    def _scalar(v):
        r = MagicMock(); r.scalar.return_value = v; return r

    db.execute = AsyncMock(side_effect=[_scalar(0), _scalars([cn])])

    def _assign_id(obj):
        if isinstance(obj, KnowledgeNode) and obj.id is None:
            obj.id = uuid.uuid4()

    db.add = MagicMock(side_effect=_assign_id)
    db.expunge = MagicMock()
    db.flush = AsyncMock(); db.commit = AsyncMock()
    mc = AsyncMock(); mc.extract = AsyncMock(return_value=(resp, {}))
    with patch("services.llm.router.get_llm_client", return_value=mc):
        result = await extract_course_concepts(db, cid)

    assert len(result) == 2
    db.expunge.assert_not_called()
