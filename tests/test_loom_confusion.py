"""Tests for services/loom_confusion.py — confusion pair detection."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.loom_confusion import _ordered_pair, detect_confusion_pairs, get_confused_concepts


# ── Pure function tests ──

def test_ordered_pair_consistent():
    """_ordered_pair always returns the same order regardless of input order."""
    a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    assert _ordered_pair(a, b) == _ordered_pair(b, a)


def test_ordered_pair_deterministic():
    """_ordered_pair returns smaller UUID first (by string comparison)."""
    a = uuid.UUID("00000000-0000-0000-0000-000000000001")
    b = uuid.UUID("00000000-0000-0000-0000-000000000002")
    assert _ordered_pair(a, b) == (a, b)
    assert _ordered_pair(b, a) == (a, b)


def test_ordered_pair_same_uuid():
    """_ordered_pair with identical UUIDs returns that pair."""
    a = uuid.uuid4()
    assert _ordered_pair(a, a) == (a, a)


# ── Async tests with mocked DB ──

@pytest.mark.asyncio
async def test_detect_confusion_pairs_no_wrong_answers():
    """Returns empty list when no wrong answers exist."""
    db = AsyncMock()
    # First query returns no wrong answers
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    result = await detect_confusion_pairs(db, uuid.uuid4(), uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_detect_confusion_pairs_with_related_concept():
    """Detects confusion via error_detail.related_concept."""
    course_id = uuid.uuid4()
    user_id = uuid.uuid4()
    node_a_id = uuid.uuid4()
    node_b_id = uuid.uuid4()

    # Create mock wrong answers with related_concept
    wa = MagicMock()
    wa.error_detail = {"related_concept": "Concept B"}
    wa.knowledge_points = ["Concept A"]
    wa.correct_answer = "correct"
    wa.user_answer = "wrong"
    wa.course_id = course_id

    # Two wrong answers to meet min_occurrences=2
    wa2 = MagicMock()
    wa2.error_detail = {"related_concept": "Concept B"}
    wa2.knowledge_points = ["Concept A"]
    wa2.correct_answer = "correct"
    wa2.user_answer = "wrong"
    wa2.course_id = course_id

    # Create mock nodes
    node_a = MagicMock()
    node_a.id = node_a_id
    node_a.name = "Concept A"
    node_a.course_id = course_id

    node_b = MagicMock()
    node_b.id = node_b_id
    node_b.name = "Concept B"
    node_b.course_id = course_id

    db = AsyncMock()

    # Setup execute calls in order:
    # 1. wrong answers query
    # 2. nodes query
    # 3. edge existence check (for each pair above threshold)
    wrong_answers_result = MagicMock()
    wrong_answers_result.scalars.return_value.all.return_value = [wa, wa2]

    nodes_result = MagicMock()
    nodes_result.scalars.return_value.all.return_value = [node_a, node_b]

    edge_result = MagicMock()
    edge_result.scalar_one_or_none.return_value = None  # no existing edge

    db.execute.side_effect = [wrong_answers_result, nodes_result, edge_result]

    result = await detect_confusion_pairs(db, course_id, user_id, min_occurrences=2)
    assert len(result) == 1
    assert result[0]["confusion_count"] == 2
    # Both concepts should be in the pair
    concepts = {result[0]["concept_a"], result[0]["concept_b"]}
    assert "Concept A" in concepts
    assert "Concept B" in concepts


@pytest.mark.asyncio
async def test_get_confused_concepts_empty():
    """Returns empty list when no nodes exist."""
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    db.execute.return_value = mock_result

    result = await get_confused_concepts(db, uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_get_confused_concepts_concept_not_found():
    """Returns empty when filtering by a concept name that doesn't exist."""
    db = AsyncMock()
    node = MagicMock()
    node.id = uuid.uuid4()
    node.name = "Existing Concept"
    node.course_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [node]
    db.execute.return_value = mock_result

    result = await get_confused_concepts(db, uuid.uuid4(), concept_name="Nonexistent")
    assert result == []
