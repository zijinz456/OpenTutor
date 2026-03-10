"""Tests for services/knowledge/graph_ops.py — graph storage and LOOM sync."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.knowledge.graph_ops import _RELATION_MAP, sync_to_knowledge_graph, store_graph_entities


# ── Pure data tests ──

def test_relation_map_completeness():
    """_RELATION_MAP maps all expected dynamic relation types."""
    assert "confused_with" in _RELATION_MAP
    assert "requires" in _RELATION_MAP
    assert "reinforces" in _RELATION_MAP
    assert "related_to" in _RELATION_MAP


def test_relation_map_values():
    """All mapped values are valid LOOM edge types."""
    valid_edge_types = {"confused_with", "prerequisite", "related"}
    for val in _RELATION_MAP.values():
        assert val in valid_edge_types, f"Unexpected edge type: {val}"


# ── sync_to_knowledge_graph tests ──

@pytest.mark.asyncio
async def test_sync_no_relationships():
    """Returns 0 when extracted dict has no relationships."""
    db = AsyncMock()
    result = await sync_to_knowledge_graph(db, uuid.uuid4(), {"relationships": []})
    assert result == 0


@pytest.mark.asyncio
async def test_sync_no_course_id():
    """Returns 0 when course_id is falsy."""
    db = AsyncMock()
    result = await sync_to_knowledge_graph(db, None, {"relationships": [{"source": "A", "target": "B", "relation": "requires"}]})
    assert result == 0


@pytest.mark.asyncio
async def test_sync_no_matching_nodes():
    """Returns 0 when no nodes match relationship source/target names."""
    db = AsyncMock()
    course_id = uuid.uuid4()

    node = MagicMock()
    node.id = uuid.uuid4()
    node.name = "Unrelated Concept"
    node.course_id = course_id

    nodes_result = MagicMock()
    nodes_result.scalars.return_value.all.return_value = [node]
    db.execute.return_value = nodes_result

    extracted = {
        "relationships": [
            {"source": "Concept A", "target": "Concept B", "relation": "requires"}
        ]
    }
    result = await sync_to_knowledge_graph(db, course_id, extracted)
    assert result == 0


@pytest.mark.asyncio
async def test_sync_creates_edge_for_matching_nodes():
    """Creates a KnowledgeEdge when source and target nodes match."""
    db = AsyncMock()
    course_id = uuid.uuid4()

    node_a = MagicMock()
    node_a.id = uuid.uuid4()
    node_a.name = "Concept A"

    node_b = MagicMock()
    node_b.id = uuid.uuid4()
    node_b.name = "Concept B"

    # First call: get nodes; second call: check existing edge
    nodes_result = MagicMock()
    nodes_result.scalars.return_value.all.return_value = [node_a, node_b]

    edge_check_result = MagicMock()
    edge_check_result.scalar_one_or_none.return_value = None

    db.execute.side_effect = [nodes_result, edge_check_result]

    extracted = {
        "relationships": [
            {"source": "Concept A", "target": "Concept B", "relation": "requires"}
        ]
    }
    result = await sync_to_knowledge_graph(db, course_id, extracted)
    assert result == 1
    assert db.add.called


# ── store_graph_entities tests ──

@pytest.mark.asyncio
async def test_store_empty_extracted():
    """Returns zeros when no entities or relationships provided."""
    db = AsyncMock()
    result = await store_graph_entities(db, uuid.uuid4(), uuid.uuid4(), {})
    assert result == {"stored_entities": 0, "stored_relationships": 0}


@pytest.mark.asyncio
async def test_store_empty_lists():
    """Returns zeros for empty entity/relationship lists."""
    db = AsyncMock()
    result = await store_graph_entities(
        db, uuid.uuid4(), uuid.uuid4(),
        {"entities": [], "relationships": []},
    )
    assert result == {"stored_entities": 0, "stored_relationships": 0}
