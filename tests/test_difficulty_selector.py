"""Tests for the adaptive difficulty selector (ZPD-based).

Covers: mastery-based layer selection, gap type overrides, FSRS state override,
DB recommendation lookup, prompt formatting.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.learning_science.difficulty_selector import (
    DifficultyRecommendation,
    recommend_difficulty,
    get_recommendation_for_node,
    format_for_prompt,
)


# ── recommend_difficulty (pure function) ──


class TestMasteryBasedSelection:
    """Mastery score determines the primary layer when no gap type is set."""

    def test_low_mastery_selects_layer_1(self):
        rec = recommend_difficulty(0.2)
        assert rec.primary_layer == 1
        assert rec.layer_distribution[1] >= 0.5
        assert "Low mastery" in rec.rationale

    def test_zero_mastery_selects_layer_1(self):
        rec = recommend_difficulty(0.0)
        assert rec.primary_layer == 1

    def test_moderate_mastery_selects_layer_2(self):
        rec = recommend_difficulty(0.5)
        assert rec.primary_layer == 2
        assert rec.layer_distribution[2] >= 0.4
        assert "Moderate mastery" in rec.rationale

    def test_boundary_0_4_selects_layer_2(self):
        rec = recommend_difficulty(0.4)
        assert rec.primary_layer == 2

    def test_high_mastery_selects_layer_3(self):
        rec = recommend_difficulty(0.85)
        assert rec.primary_layer == 3
        assert rec.layer_distribution[3] >= 0.5
        assert "High mastery" in rec.rationale

    def test_boundary_0_7_selects_layer_3(self):
        rec = recommend_difficulty(0.7)
        assert rec.primary_layer == 3

    def test_max_mastery(self):
        rec = recommend_difficulty(1.0)
        assert rec.primary_layer == 3

    def test_distribution_sums_to_1(self):
        for mastery in [0.0, 0.2, 0.4, 0.5, 0.7, 0.85, 1.0]:
            rec = recommend_difficulty(mastery)
            total = sum(rec.layer_distribution.values())
            assert abs(total - 1.0) < 0.01, f"mastery={mastery}: distribution sums to {total}"


class TestGapTypeOverrides:
    """Gap type forces a specific layer regardless of mastery."""

    def test_fundamental_gap_forces_layer_1(self):
        rec = recommend_difficulty(0.9, gap_type="fundamental_gap")
        assert rec.primary_layer == 1
        assert "Fundamental gap" in rec.rationale
        assert rec.gap_type == "fundamental_gap"

    def test_transfer_gap_forces_layer_2(self):
        rec = recommend_difficulty(0.1, gap_type="transfer_gap")
        assert rec.primary_layer == 2
        assert "Transfer gap" in rec.rationale

    def test_trap_vulnerability_forces_layer_3(self):
        rec = recommend_difficulty(0.3, gap_type="trap_vulnerability")
        assert rec.primary_layer == 3
        assert "Trap vulnerability" in rec.rationale

    def test_unknown_gap_type_falls_through(self):
        rec = recommend_difficulty(0.5, gap_type="unknown_gap")
        assert rec.primary_layer == 2  # mastery-based


class TestFsrsStateOverride:
    """FSRS relearning state forces easier questions."""

    def test_relearning_forces_layer_1(self):
        rec = recommend_difficulty(0.8, fsrs_state="relearning")
        assert rec.primary_layer == 1
        assert "Relearning" in rec.rationale

    def test_relearning_overridden_by_gap_type(self):
        # Gap type takes precedence over FSRS state
        rec = recommend_difficulty(0.8, gap_type="trap_vulnerability", fsrs_state="relearning")
        assert rec.primary_layer == 3

    def test_normal_fsrs_state_ignored(self):
        rec = recommend_difficulty(0.8, fsrs_state="learning")
        assert rec.primary_layer == 3  # mastery-based


class TestMasteryScorePreserved:
    """Mastery score is always preserved in the recommendation."""

    def test_mastery_stored(self):
        for m in [0.0, 0.5, 1.0]:
            assert recommend_difficulty(m).mastery_score == m

    def test_gap_type_stored(self):
        rec = recommend_difficulty(0.5, gap_type="transfer_gap")
        assert rec.gap_type == "transfer_gap"

    def test_none_gap_stored(self):
        rec = recommend_difficulty(0.5)
        assert rec.gap_type is None


# ── get_recommendation_for_node (DB integration) ──


@pytest.mark.asyncio
async def test_recommendation_no_progress():
    """No progress record → treat as mastery 0.0."""
    db = AsyncMock()
    rm = MagicMock()
    rm.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=rm)

    rec = await get_recommendation_for_node(db, uuid.uuid4(), uuid.uuid4())
    assert rec.primary_layer == 1 and rec.mastery_score == 0.0


@pytest.mark.asyncio
async def test_recommendation_with_progress():
    """Progress record maps to appropriate difficulty."""
    db = AsyncMock()
    progress = SimpleNamespace(mastery_score=0.6, gap_type=None, fsrs_state=None)
    rm = MagicMock()
    rm.scalar_one_or_none.return_value = progress
    db.execute = AsyncMock(return_value=rm)

    rec = await get_recommendation_for_node(db, uuid.uuid4(), uuid.uuid4())
    assert rec.primary_layer == 2


@pytest.mark.asyncio
async def test_recommendation_with_gap_type():
    """Progress with gap type applies override."""
    db = AsyncMock()
    progress = SimpleNamespace(mastery_score=0.8, gap_type="fundamental_gap", fsrs_state=None)
    rm = MagicMock()
    rm.scalar_one_or_none.return_value = progress
    db.execute = AsyncMock(return_value=rm)

    rec = await get_recommendation_for_node(db, uuid.uuid4(), uuid.uuid4())
    assert rec.primary_layer == 1  # gap overrides mastery


@pytest.mark.asyncio
async def test_recommendation_with_content_node():
    """Content node ID is passed to the query."""
    db = AsyncMock()
    rm = MagicMock()
    rm.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=rm)

    node_id = uuid.uuid4()
    await get_recommendation_for_node(db, uuid.uuid4(), uuid.uuid4(), content_node_id=node_id)
    db.execute.assert_awaited_once()


# ── format_for_prompt ──


class TestFormatForPrompt:
    def test_contains_layer_and_rationale(self):
        rec = DifficultyRecommendation(
            primary_layer=2,
            layer_distribution={1: 0.2, 2: 0.5, 3: 0.3},
            rationale="Test rationale",
            mastery_score=0.5,
            gap_type=None,
        )
        text = format_for_prompt(rec)
        assert "Recommended primary layer: 2" in text
        assert "Test rationale" in text
        assert "Layer 1:" in text and "Layer 2:" in text and "Layer 3:" in text

    def test_contains_adaptive_header(self):
        rec = recommend_difficulty(0.5)
        text = format_for_prompt(rec)
        assert "[ADAPTIVE DIFFICULTY GUIDANCE]" in text

    def test_distribution_percentages(self):
        rec = DifficultyRecommendation(
            primary_layer=1,
            layer_distribution={1: 0.7, 2: 0.3, 3: 0.0},
            rationale="test",
            mastery_score=0.2,
            gap_type="fundamental_gap",
        )
        text = format_for_prompt(rec)
        assert "70%" in text and "30%" in text and "0%" in text
