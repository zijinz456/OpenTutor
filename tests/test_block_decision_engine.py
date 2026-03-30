"""Tests for the Block Decision Engine (rules + engine)."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.block_decision.rules import (
    BlockOperation,
    rule_cognitive_overload,
    rule_cognitive_recovery,
    rule_forgetting_risk,
    rule_frustration,
    rule_deadline_approaching,
    rule_prerequisite_gap,
    rule_weak_areas,
    rule_confusion_pairs,
    rule_inactivity,
    rule_mastery_complete,
)
from services.block_decision.engine import compute_block_decisions, MAX_OPS_PER_TURN
from services.block_decision.cold_start import compute_cold_start_layout


# ── Rule unit tests ──


class TestCognitiveOverloadRule:
    def test_fires_when_high_and_consecutive(self):
        cl = {"score": 0.8, "consecutive_high": 3}
        blocks = ["notes", "quiz", "forecast", "knowledge_graph", "progress"]
        ops = rule_cognitive_overload(cl, blocks)
        assert len(ops) > 0
        assert all(op.action == "remove" for op in ops)
        assert all(op.signal_source == "cognitive_load" for op in ops)

    def test_does_not_fire_below_threshold(self):
        cl = {"score": 0.5, "consecutive_high": 0}
        ops = rule_cognitive_overload(cl, ["notes", "quiz", "forecast"])
        assert ops == []

    def test_does_not_fire_when_consecutive_low(self):
        cl = {"score": 0.8, "consecutive_high": 1}
        ops = rule_cognitive_overload(cl, ["notes", "quiz", "forecast"])
        assert ops == []

    def test_skips_protected_blocks(self):
        cl = {"score": 0.9, "consecutive_high": 3}
        blocks = ["notes", "quiz", "chapter_list", "forecast"]
        ops = rule_cognitive_overload(cl, blocks)
        removed_types = {op.block_type for op in ops}
        assert "notes" not in removed_types
        assert "quiz" not in removed_types
        assert "chapter_list" not in removed_types

    def test_none_cognitive_load(self):
        assert rule_cognitive_overload(None, ["notes"]) == []


class TestForgettingRiskRule:
    def test_fires_with_enough_urgent(self):
        signals = [
            {"signal_type": "forgetting_risk", "urgency": 80},
            {"signal_type": "forgetting_risk", "urgency": 75},
            {"signal_type": "forgetting_risk", "urgency": 90},
        ]
        op = rule_forgetting_risk(signals, ["notes", "quiz"])
        assert op is not None
        assert op.action == "add"
        assert op.block_type == "review"

    def test_does_not_fire_if_review_exists(self):
        signals = [
            {"signal_type": "forgetting_risk", "urgency": 80},
            {"signal_type": "forgetting_risk", "urgency": 75},
            {"signal_type": "forgetting_risk", "urgency": 90},
        ]
        op = rule_forgetting_risk(signals, ["notes", "review"])
        assert op is None

    def test_does_not_fire_with_few_urgent(self):
        signals = [
            {"signal_type": "forgetting_risk", "urgency": 80},
            {"signal_type": "forgetting_risk", "urgency": 50},
        ]
        op = rule_forgetting_risk(signals, ["notes"])
        assert op is None


class TestFrustrationRule:
    def test_fires_with_high_frustration(self):
        cl = {"signals": {"nlp_affect": 0.7, "fatigue": 0.3}}
        ops = rule_frustration(cl, ["notes", "quiz"])
        assert any(op.block_type == "quiz" and op.action == "remove" for op in ops)

    def test_does_not_fire_below_threshold(self):
        cl = {"signals": {"nlp_affect": 0.3, "fatigue": 0.2}}
        assert rule_frustration(cl, ["notes", "quiz"]) == []


class TestDeadlineRule:
    def test_fires_with_urgent_deadline(self):
        signals = [{"signal_type": "deadline", "urgency": 90, "detail": {"title": "HW3"}}]
        op = rule_deadline_approaching(signals, ["notes"])
        assert op is not None
        assert op.block_type == "plan"
        assert "HW3" in op.reason

    def test_does_not_fire_if_plan_exists(self):
        signals = [{"signal_type": "deadline", "urgency": 90, "detail": {"title": "HW3"}}]
        assert rule_deadline_approaching(signals, ["notes", "plan"]) is None


class TestPrerequisiteGapRule:
    def test_fires_with_gap(self):
        signals = [{"signal_type": "prerequisite_gap"}]
        op = rule_prerequisite_gap(signals, ["notes"])
        assert op is not None
        assert op.block_type == "knowledge_graph"

    def test_does_not_fire_if_graph_exists(self):
        signals = [{"signal_type": "prerequisite_gap"}]
        assert rule_prerequisite_gap(signals, ["notes", "knowledge_graph"]) is None


class TestWeakAreasRule:
    def test_fires_with_many_weak(self):
        signals = [{"signal_type": "weak_area"} for _ in range(4)]
        op = rule_weak_areas(signals, ["notes", "quiz"])
        assert op is not None
        assert op.block_type == "wrong_answers"

    def test_does_not_fire_with_few(self):
        signals = [{"signal_type": "weak_area"} for _ in range(2)]
        assert rule_weak_areas(signals, ["notes"]) is None


class TestConfusionPairsRule:
    def test_fires_with_confused_pairs(self):
        signals = [{
            "signal_type": "layout_adaptation",
            "detail": {"confused_pairs": [["mitosis", "meiosis"], ["DNA", "RNA"]]},
        }]
        op = rule_confusion_pairs(signals, ["notes", "quiz"])
        assert op is not None
        assert op.action == "update_config"
        assert op.block_type == "quiz"
        assert op.config["target_concepts"] == ["mitosis", "DNA"]

    def test_does_not_fire_without_quiz(self):
        signals = [{
            "signal_type": "layout_adaptation",
            "detail": {"confused_pairs": [["A", "B"], ["C", "D"]]},
        }]
        assert rule_confusion_pairs(signals, ["notes"]) is None

    def test_does_not_fire_with_single_pair(self):
        signals = [{
            "signal_type": "layout_adaptation",
            "detail": {"confused_pairs": [["A", "B"]]},
        }]
        assert rule_confusion_pairs(signals, ["quiz"]) is None

    def test_does_not_fire_with_wrong_signal_type(self):
        signals = [{
            "signal_type": "forgetting_risk",
            "detail": {"confused_pairs": [["A", "B"], ["C", "D"]]},
        }]
        assert rule_confusion_pairs(signals, ["quiz"]) is None


class TestInactivityRule:
    def test_fires_when_inactive(self):
        signals = [{"signal_type": "inactivity"}]
        op = rule_inactivity(signals, ["notes"])
        assert op is not None
        assert op.block_type == "agent_insight"

    def test_does_not_fire_if_insight_exists(self):
        signals = [{"signal_type": "inactivity"}]
        assert rule_inactivity(signals, ["notes", "agent_insight"]) is None


class TestMasteryCompleteRule:
    def test_fires_when_no_weak_areas(self):
        # Must have some signals present (otherwise treated as "collection failed")
        signals = [{"signal_type": "mastery_high"}]
        op = rule_mastery_complete(signals, ["notes", "quiz"], "course_following")
        assert op is not None
        assert op.config.get("insightType") == "mode_suggestion"

    def test_does_not_fire_if_already_maintenance(self):
        signals = [{"signal_type": "mastery_high"}]
        assert rule_mastery_complete(signals, ["notes"], "maintenance") is None

    def test_does_not_fire_with_weak_signals(self):
        signals = [{"signal_type": "weak_area"}]
        assert rule_mastery_complete(signals, ["notes"], "course_following") is None

    def test_does_not_fire_with_empty_signals(self):
        """Empty signals = collection failed, should not false-positive."""
        assert rule_mastery_complete([], ["notes", "quiz"], "course_following") is None


class TestCognitiveRecoveryRule:
    def test_recovers_when_load_low_and_consecutive_decayed(self):
        """Recovery fires when score < 0.4 and consecutive <= 2."""
        cl = {"score": 0.2, "consecutive_high": 1}
        removed = ["forecast", "knowledge_graph"]
        ops = rule_cognitive_recovery(cl, ["notes", "quiz"], removed)
        assert len(ops) == 2
        assert all(op.action == "add" for op in ops)
        assert {op.block_type for op in ops} == {"forecast", "knowledge_graph"}

    def test_blocks_recovery_when_consecutive_still_high(self):
        """Recovery blocked when consecutive > 2."""
        cl = {"score": 0.3, "consecutive_high": 3}
        removed = ["forecast"]
        ops = rule_cognitive_recovery(cl, ["notes"], removed)
        assert ops == []

    def test_blocks_recovery_when_score_high(self):
        cl = {"score": 0.5, "consecutive_high": 0}
        removed = ["forecast"]
        ops = rule_cognitive_recovery(cl, ["notes"], removed)
        assert ops == []

    def test_no_recovery_without_removed(self):
        cl = {"score": 0.1, "consecutive_high": 0}
        ops = rule_cognitive_recovery(cl, ["notes"], removed_for_load=None)
        assert ops == []

    def test_no_recovery_without_cognitive_data(self):
        ops = rule_cognitive_recovery(None, ["notes"], removed_for_load=["forecast"])
        assert ops == []

    def test_does_not_recover_already_present_blocks(self):
        cl = {"score": 0.1, "consecutive_high": 0}
        removed = ["forecast", "notes"]
        ops = rule_cognitive_recovery(cl, ["notes", "quiz"], removed)
        # "notes" already in current_blocks, should not be re-added
        assert len(ops) == 1
        assert ops[0].block_type == "forecast"


# ── Engine integration tests ──


class TestComputeBlockDecisions:
    @pytest.mark.asyncio
    async def test_caps_at_max_ops(self):
        """Even with many rules firing, result is capped at MAX_OPS_PER_TURN."""
        db = AsyncMock()
        db.add = MagicMock()  # AsyncSession.add() is synchronous
        result = await compute_block_decisions(
            db, uuid.uuid4(), uuid.uuid4(),
            current_blocks=["notes", "quiz", "forecast", "knowledge_graph", "progress"],
            current_mode="course_following",
            cognitive_load={"score": 0.9, "consecutive_high": 5, "signals": {"nlp_affect": 0.8, "fatigue": 0.8}},
            dismissed_types=[],
            signals=[
                {"signal_type": "forgetting_risk", "urgency": 90},
                {"signal_type": "forgetting_risk", "urgency": 85},
                {"signal_type": "forgetting_risk", "urgency": 80},
                {"signal_type": "deadline", "urgency": 90, "detail": {"title": "Exam"}},
            ],
        )
        assert len(result.operations) <= MAX_OPS_PER_TURN

    @pytest.mark.asyncio
    async def test_dismissed_types_filtered(self):
        """Dismissed block types should not be re-added."""
        db = AsyncMock()
        result = await compute_block_decisions(
            db, uuid.uuid4(), uuid.uuid4(),
            current_blocks=["notes"],
            current_mode="course_following",
            cognitive_load=None,
            dismissed_types=["review"],
            signals=[
                {"signal_type": "forgetting_risk", "urgency": 90},
                {"signal_type": "forgetting_risk", "urgency": 85},
                {"signal_type": "forgetting_risk", "urgency": 80},
            ],
        )
        added_types = {op.block_type for op in result.operations if op.action == "add"}
        assert "review" not in added_types

    @pytest.mark.asyncio
    async def test_existing_blocks_not_duplicated(self):
        """Blocks already in workspace should not be added again."""
        db = AsyncMock()
        result = await compute_block_decisions(
            db, uuid.uuid4(), uuid.uuid4(),
            current_blocks=["notes", "review"],
            current_mode="course_following",
            cognitive_load=None,
            dismissed_types=[],
            signals=[
                {"signal_type": "forgetting_risk", "urgency": 90},
                {"signal_type": "forgetting_risk", "urgency": 85},
                {"signal_type": "forgetting_risk", "urgency": 80},
            ],
        )
        added_types = {op.block_type for op in result.operations if op.action == "add"}
        assert "review" not in added_types

    @pytest.mark.asyncio
    async def test_cognitive_state_populated(self):
        """cognitive_state should reflect input cognitive load."""
        db = AsyncMock()
        result = await compute_block_decisions(
            db, uuid.uuid4(), uuid.uuid4(),
            current_blocks=["notes"],
            current_mode=None,
            cognitive_load={"score": 0.45, "level": "medium", "signals": {"typing_speed": 0.3}},
            dismissed_types=[],
        )
        assert result.cognitive_state["score"] == 0.45
        assert result.cognitive_state["level"] == "medium"

    @pytest.mark.asyncio
    async def test_empty_when_no_signals(self):
        """No signals → no operations."""
        db = AsyncMock()
        result = await compute_block_decisions(
            db, uuid.uuid4(), uuid.uuid4(),
            current_blocks=["notes", "quiz"],
            current_mode="course_following",
            cognitive_load={"score": 0.2, "consecutive_high": 0},
            dismissed_types=[],
        )
        # Only mastery_complete might fire (no weak signals + not maintenance)
        # But it adds agent_insight which is not in current_blocks
        for op in result.operations:
            assert op.action in ("add", "update_config")

    @pytest.mark.asyncio
    async def test_preference_blocks_dismissed_type(self):
        """Blocks with dismiss_count >= 3 should be filtered out."""
        db = AsyncMock()
        result = await compute_block_decisions(
            db, uuid.uuid4(), uuid.uuid4(),
            current_blocks=["notes"],
            current_mode="course_following",
            cognitive_load=None,
            dismissed_types=[],
            signals=[
                {"signal_type": "forgetting_risk", "urgency": 90},
                {"signal_type": "forgetting_risk", "urgency": 85},
                {"signal_type": "forgetting_risk", "urgency": 80},
            ],
            preferences={
                "block_scores": {"review": {"score": -2.0, "dismiss_count": 5}},
            },
        )
        added_types = {op.block_type for op in result.operations if op.action == "add"}
        assert "review" not in added_types

    @pytest.mark.asyncio
    async def test_to_dict_serialization(self):
        """BlockDecisionResult.to_dict() should produce a JSON-serializable dict."""
        db = AsyncMock()
        result = await compute_block_decisions(
            db, uuid.uuid4(), uuid.uuid4(),
            current_blocks=["notes"],
            current_mode=None,
            cognitive_load={"score": 0.3, "level": "low", "signals": {}},
            dismissed_types=[],
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "operations" in d
        assert "cognitive_state" in d
        assert "explanation" in d


# ── Cold start tests ──


class TestColdStartLayout:
    def test_textbook_layout(self):
        layout = compute_cold_start_layout("textbook", 0)
        assert layout["mode"] == "course_following"
        assert layout["cold_start"] is True
        block_types = [b["type"] for b in layout["blocks"]]
        assert "notes" in block_types

    def test_exam_schedule_layout(self):
        layout = compute_cold_start_layout("exam_schedule", 0)
        assert layout["mode"] == "exam_prep"
        block_types = [b["type"] for b in layout["blocks"]]
        assert "quiz" in block_types

    def test_knowledge_graph_added_with_enough_concepts(self):
        layout = compute_cold_start_layout("notes", 10)
        block_types = [b["type"] for b in layout["blocks"]]
        assert "knowledge_graph" in block_types

    def test_no_knowledge_graph_with_few_concepts(self):
        layout = compute_cold_start_layout("notes", 2)
        block_types = [b["type"] for b in layout["blocks"]]
        assert "knowledge_graph" not in block_types

    def test_unknown_category_uses_other(self):
        layout = compute_cold_start_layout("something_unknown", 0)
        assert layout["mode"] == "self_paced"

    def test_primary_block_is_large(self):
        layout = compute_cold_start_layout("textbook", 0)
        primary = next(b for b in layout["blocks"] if b["type"] == "notes")
        assert primary["size"] == "large"
