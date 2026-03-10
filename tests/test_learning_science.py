"""Tests for learning science services: velocity tracker, completion forecaster, transfer detector.

Covers:
- compute_velocity(): zero concepts, single snapshot, multiple snapshots,
  accelerating/steady/decelerating trends, mastery threshold boundary
- forecast_completion(): already complete, no velocity, normal 3-point estimates,
  confidence levels (high/medium/low), trend adjustments
- detect_transfer_opportunities(): no edges, with reinforces edges, mastery thresholds,
  result ordering, limit cap

Model column patches are applied in conftest.py.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_row(*values):
    """Return a mock row that supports integer indexing."""
    row = MagicMock()
    row.__getitem__ = lambda self, idx: values[idx]
    return row


def _mock_one_result(*values):
    """Return a mock query result whose .one() returns a row with *values*."""
    row = _mock_row(*values)
    result = MagicMock()
    result.one.return_value = row
    return result


def _mock_scalars_result(items):
    """Return a mock result whose .scalars().all() returns *items*."""
    scalars = MagicMock()
    scalars.all.return_value = items
    result = MagicMock()
    result.scalars.return_value = scalars
    return result


def _mock_scalar_result(value):
    """Return a mock result whose .scalar() returns *value*."""
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _make_snapshot(mastery_score: float, recorded_at: datetime):
    """Build a mock MasterySnapshot."""
    snap = MagicMock()
    snap.mastery_score = mastery_score
    snap.recorded_at = recorded_at
    return snap


def _make_node(nid, cid, text="Concept"):
    """Build a mock KnowledgeNode with both .label and .name attributes."""
    n = MagicMock()
    n.id = str(nid)
    n.course_id = str(cid)
    # Service code uses .label; actual model uses .name. Set both.
    n.label = text
    n.name = text
    return n


def _make_kg_edge(src_nid, tgt_nid, etype="reinforces"):
    """Build a mock KnowledgeEdge with both naming conventions."""
    e = MagicMock()
    # Service code uses source_node_id / target_node_id / edge_type
    e.source_node_id = src_nid
    e.target_node_id = tgt_nid
    e.edge_type = etype
    # Actual model uses source_id / target_id / relation_type
    e.source_id = src_nid
    e.target_id = tgt_nid
    e.relation_type = etype
    return e


def _make_mastery_mock(nid, score):
    """Build a mock ConceptMastery row returned by scalars."""
    m = MagicMock()
    m.node_id = str(nid)
    m.knowledge_node_id = str(nid)
    m.mastery_score = score
    return m


# ===========================================================================
# Velocity Tracker
# ===========================================================================


class TestComputeVelocity:
    """Tests for services.learning_science.velocity_tracker.compute_velocity."""

    @pytest.mark.asyncio
    async def test_zero_concepts_returns_empty(self):
        """When no concepts exist, all metrics should be zero/steady."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_one_result(0, 0, None))

        result = await compute_velocity(db, uuid.uuid4())

        assert result["concepts_total"] == 0
        assert result["concepts_mastered"] == 0
        assert result["mastery_rate"] == 0.0
        assert result["avg_mastery"] == 0.0
        assert result["concepts_per_day"] == 0.0
        assert result["velocity_trend"] == "steady"
        assert result["window_days"] == 7

    @pytest.mark.asyncio
    async def test_single_snapshot_stays_steady(self):
        """With only one snapshot, velocity should be zero and trend steady."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        now = datetime.now(timezone.utc)

        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(5, 2, 0.5)
            return _mock_scalars_result([_make_snapshot(0.4, now)])

        db.execute = AsyncMock(side_effect=_exec)

        result = await compute_velocity(db, uuid.uuid4())

        assert result["concepts_total"] == 5
        assert result["concepts_mastered"] == 2
        assert result["mastery_rate"] == pytest.approx(0.4)
        assert result["avg_mastery"] == 0.5
        assert result["concepts_per_day"] == 0.0
        assert result["velocity_trend"] == "steady"

    @pytest.mark.asyncio
    async def test_two_snapshots_computes_velocity(self):
        """Two snapshots should produce a non-zero concepts_per_day."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        now = datetime.now(timezone.utc)
        snaps = [
            _make_snapshot(0.2, now - timedelta(days=4)),
            _make_snapshot(0.6, now),
        ]
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(10, 3, 0.55)
            return _mock_scalars_result(snaps)

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())

        # mastery_gain = 0.4, days = 4, total = 10 => cpd = 1.0
        assert result["concepts_per_day"] == 1.0
        assert result["concepts_total"] == 10
        assert result["concepts_mastered"] == 3

    @pytest.mark.asyncio
    async def test_accelerating_trend(self):
        """Second half gaining faster than first half * 1.2 => accelerating."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        now = datetime.now(timezone.utc)
        snaps = [
            _make_snapshot(0.10, now - timedelta(days=6)),
            _make_snapshot(0.15, now - timedelta(days=4)),
            _make_snapshot(0.20, now - timedelta(days=2)),
            _make_snapshot(0.40, now),
        ]
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(8, 2, 0.4)
            return _mock_scalars_result(snaps)

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        assert result["velocity_trend"] == "accelerating"

    @pytest.mark.asyncio
    async def test_decelerating_trend(self):
        """Second half gaining slower than first half * 0.8 => decelerating."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        now = datetime.now(timezone.utc)
        snaps = [
            _make_snapshot(0.10, now - timedelta(days=6)),
            _make_snapshot(0.40, now - timedelta(days=4)),
            _make_snapshot(0.42, now - timedelta(days=2)),
            _make_snapshot(0.45, now),
        ]
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(10, 4, 0.45)
            return _mock_scalars_result(snaps)

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        assert result["velocity_trend"] == "decelerating"

    @pytest.mark.asyncio
    async def test_steady_trend_when_halves_similar(self):
        """When first and second half gains are within 20%, trend is steady."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        now = datetime.now(timezone.utc)
        # midpoint = 4 // 2 = 2, so first_half=[0.20, 0.30] gain=0.10
        # second_half=[0.30, 0.40] gain=0.10  =>  0.10 is within [0.08, 0.12]
        snaps = [
            _make_snapshot(0.20, now - timedelta(days=6)),
            _make_snapshot(0.30, now - timedelta(days=4)),
            _make_snapshot(0.30, now - timedelta(days=2)),
            _make_snapshot(0.40, now),
        ]
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(6, 1, 0.35)
            return _mock_scalars_result(snaps)

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        assert result["velocity_trend"] == "steady"

    @pytest.mark.asyncio
    async def test_mastery_threshold_constant(self):
        """MASTERY_THRESHOLD should be 0.8."""
        from services.learning_science.velocity_tracker import MASTERY_THRESHOLD

        assert MASTERY_THRESHOLD == 0.8

    @pytest.mark.asyncio
    async def test_mastery_threshold_boundary(self):
        """Concepts exactly at 0.8 should count as mastered."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(3, 1, 0.6)
            return _mock_scalars_result([])

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        assert result["concepts_mastered"] == 1
        assert result["mastery_rate"] == pytest.approx(1 / 3)

    @pytest.mark.asyncio
    async def test_custom_window_days(self):
        """window_days parameter should be reflected in result."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_one_result(0, 0, None))

        result = await compute_velocity(db, uuid.uuid4(), window_days=30)
        assert result["window_days"] == 30

    @pytest.mark.asyncio
    async def test_avg_mastery_rounded_to_three_decimals(self):
        """avg_mastery should be rounded to 3 decimal places."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(5, 2, 0.33333333)
            return _mock_scalars_result([])

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        assert result["avg_mastery"] == 0.333

    @pytest.mark.asyncio
    async def test_no_snapshots_gives_zero_velocity(self):
        """Having concepts but no snapshots should give zero concepts_per_day."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(10, 5, 0.7)
            return _mock_scalars_result([])

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        assert result["concepts_per_day"] == 0.0
        assert result["velocity_trend"] == "steady"
        assert result["concepts_total"] == 10

    @pytest.mark.asyncio
    async def test_very_close_snapshots_use_min_day_floor(self):
        """Snapshots taken seconds apart should use 0.1 day floor for division."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        now = datetime.now(timezone.utc)
        snaps = [
            _make_snapshot(0.0, now - timedelta(seconds=1)),
            _make_snapshot(0.5, now),
        ]
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(4, 1, 0.4)
            return _mock_scalars_result(snaps)

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        # days_elapsed = max(1/86400, 0.1) = 0.1; cpd = 0.5 * 4 / 0.1 = 20.0
        assert result["concepts_per_day"] == 20.0

    @pytest.mark.asyncio
    async def test_concepts_per_day_rounded_to_two_decimals(self):
        """concepts_per_day should be rounded to 2 decimal places."""
        from services.learning_science.velocity_tracker import compute_velocity

        db = AsyncMock()
        now = datetime.now(timezone.utc)
        snaps = [
            _make_snapshot(0.0, now - timedelta(days=3)),
            _make_snapshot(0.1, now),
        ]
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_one_result(7, 0, 0.1)
            return _mock_scalars_result(snaps)

        db.execute = AsyncMock(side_effect=_exec)
        result = await compute_velocity(db, uuid.uuid4())
        # 0.1 * 7 / 3 = 0.23333... => 0.23
        assert result["concepts_per_day"] == 0.23


# ===========================================================================
# Completion Forecaster
# ===========================================================================


class TestForecastCompletion:
    """Tests for services.learning_science.completion_forecaster.forecast_completion."""

    @pytest.mark.asyncio
    async def test_empty_course_returns_empty_forecast(self):
        """No concepts at all should return the empty forecast."""
        from services.learning_science.completion_forecaster import forecast_completion

        vel = {
            "concepts_total": 0, "concepts_mastered": 0, "mastery_rate": 0.0,
            "avg_mastery": 0.0, "concepts_per_day": 0.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(AsyncMock(), uuid.uuid4())

        assert result["is_complete"] is False
        assert result["concepts_remaining"] == 0
        assert result["optimistic_days"] is None
        assert result["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_already_complete(self):
        """All concepts mastered should return is_complete=True."""
        from services.learning_science.completion_forecaster import forecast_completion

        vel = {
            "concepts_total": 10, "concepts_mastered": 10, "mastery_rate": 1.0,
            "avg_mastery": 0.95, "concepts_per_day": 2.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(AsyncMock(), uuid.uuid4())

        assert result["is_complete"] is True
        assert result["concepts_remaining"] == 0
        assert result["optimistic_days"] == 0
        assert result["expected_days"] == 0
        assert result["pessimistic_days"] == 0
        assert result["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_no_velocity_returns_unpredictable(self):
        """Zero velocity should return None for all date estimates."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 10, "concepts_mastered": 3, "mastery_rate": 0.3,
            "avg_mastery": 0.4, "concepts_per_day": 0.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.3))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        assert result["is_complete"] is False
        assert result["concepts_remaining"] == 7
        assert result["optimistic_days"] is None
        assert result["expected_days"] is None
        assert result["pessimistic_days"] is None
        assert result["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_normal_forecast_three_point_estimates(self):
        """Normal velocity should produce optimistic < expected < pessimistic."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 20, "concepts_mastered": 10, "mastery_rate": 0.5,
            "avg_mastery": 0.6, "concepts_per_day": 2.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.4))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        assert result["is_complete"] is False
        assert result["concepts_remaining"] == 10
        # remaining/cpd = 10/2 = 5.0
        assert result["expected_days"] == 5.0
        assert result["optimistic_days"] == pytest.approx(5.0 * 0.6, abs=0.1)
        assert result["pessimistic_days"] == pytest.approx(5.0 * 1.8, abs=0.1)
        assert result["optimistic_days"] < result["expected_days"] < result["pessimistic_days"]
        assert result["optimistic_date"] is not None
        assert result["expected_date"] is not None
        assert result["pessimistic_date"] is not None

    @pytest.mark.asyncio
    async def test_confidence_high_with_enough_mastered(self):
        """cpd > 0 and mastered >= 5 should give high confidence."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 20, "concepts_mastered": 8, "mastery_rate": 0.4,
            "avg_mastery": 0.5, "concepts_per_day": 1.5,
            "velocity_trend": "steady", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.3))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        assert result["confidence"] == "high"

    @pytest.mark.asyncio
    async def test_confidence_low_with_few_mastered(self):
        """mastered < 2 should give low confidence."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 20, "concepts_mastered": 1, "mastery_rate": 0.05,
            "avg_mastery": 0.1, "concepts_per_day": 0.5,
            "velocity_trend": "steady", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.1))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        assert result["confidence"] == "low"

    @pytest.mark.asyncio
    async def test_confidence_medium_default(self):
        """mastered in [2, 4] with positive cpd should give medium confidence."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 20, "concepts_mastered": 3, "mastery_rate": 0.15,
            "avg_mastery": 0.25, "concepts_per_day": 1.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.2))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        assert result["confidence"] == "medium"

    @pytest.mark.asyncio
    async def test_accelerating_trend_adjusts_estimates_down(self):
        """Accelerating trend should reduce optimistic and expected days."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 20, "concepts_mastered": 10, "mastery_rate": 0.5,
            "avg_mastery": 0.6, "concepts_per_day": 2.0,
            "velocity_trend": "accelerating", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.4))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        # base expected = 5.0, * 0.9 = 4.5
        assert result["expected_days"] == pytest.approx(4.5, abs=0.1)
        # optimistic = 5.0 * 0.6 * 0.8 = 2.4
        assert result["optimistic_days"] == pytest.approx(2.4, abs=0.1)

    @pytest.mark.asyncio
    async def test_decelerating_trend_adjusts_estimates_up(self):
        """Decelerating trend should increase expected and pessimistic days."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 20, "concepts_mastered": 10, "mastery_rate": 0.5,
            "avg_mastery": 0.6, "concepts_per_day": 2.0,
            "velocity_trend": "decelerating", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.4))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        # base expected = 5.0, * 1.2 = 6.0
        assert result["expected_days"] == pytest.approx(6.0, abs=0.1)
        # pessimistic = 5.0 * 1.8 * 1.3 = 11.7
        assert result["pessimistic_days"] == pytest.approx(11.7, abs=0.1)

    @pytest.mark.asyncio
    async def test_avg_gap_computed_correctly(self):
        """avg_gap should be MASTERY_THRESHOLD minus the avg score of unmastered concepts."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 10, "concepts_mastered": 5, "mastery_rate": 0.5,
            "avg_mastery": 0.6, "concepts_per_day": 1.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        # avg_unmastered = 0.35 => gap = 0.8 - 0.35 = 0.45
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.35))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        assert result["avg_gap"] == pytest.approx(0.45, abs=0.001)

    @pytest.mark.asyncio
    async def test_avg_gap_null_unmastered_defaults_to_full_gap(self):
        """If avg unmastered is None, gap should be MASTERY_THRESHOLD (0.8)."""
        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 10, "concepts_mastered": 5, "mastery_rate": 0.5,
            "avg_mastery": 0.6, "concepts_per_day": 1.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(None))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        assert result["avg_gap"] == pytest.approx(0.8, abs=0.001)

    @pytest.mark.asyncio
    async def test_forecast_dates_are_iso_format(self):
        """Forecast dates should be valid ISO date strings."""
        from datetime import date as date_cls

        from services.learning_science.completion_forecaster import forecast_completion

        db = AsyncMock()
        vel = {
            "concepts_total": 10, "concepts_mastered": 5, "mastery_rate": 0.5,
            "avg_mastery": 0.6, "concepts_per_day": 1.0,
            "velocity_trend": "steady", "window_days": 14,
        }
        db.execute = AsyncMock(return_value=_mock_scalar_result(0.3))

        with patch(
            "services.learning_science.completion_forecaster.compute_velocity",
            new_callable=AsyncMock, return_value=vel,
        ):
            result = await forecast_completion(db, uuid.uuid4())

        for key in ("optimistic_date", "expected_date", "pessimistic_date"):
            date_cls.fromisoformat(result[key])


# ===========================================================================
# Transfer Detector
# ===========================================================================


class TestDetectTransferOpportunities:
    """Tests for services.learning_science.transfer_detector.detect_transfer_opportunities."""

    def _setup_transfer_db(self, edges, mastery_mocks, node_mocks):
        """Build an AsyncMock db that returns edges, masteries, nodes in order."""
        db = AsyncMock()
        call_count = 0

        async def _exec(stmt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_scalars_result(edges)
            if call_count == 2:
                return _mock_scalars_result(mastery_mocks)
            return _mock_scalars_result(node_mocks)

        db.execute = AsyncMock(side_effect=_exec)
        return db

    @pytest.mark.asyncio
    async def test_no_edges_returns_empty(self):
        """When no reinforces edges exist, return empty list."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_mock_scalars_result([]))

        result = await detect_transfer_opportunities(db, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_cross_course_transfer_detected(self):
        """A mastered source with unmastered target across courses should produce a recommendation."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[_make_mastery_mock(nid_a, 0.9), _make_mastery_mock(nid_b, 0.2)],
            node_mocks=[
                _make_node(nid_a, cid_a, "Linear Algebra"),
                _make_node(nid_b, cid_b, "Matrix Transformations"),
            ],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())

        assert len(result) == 1
        rec = result[0]
        assert rec["source_concept"] == "Linear Algebra"
        assert rec["target_concept"] == "Matrix Transformations"
        assert rec["source_mastery"] == 0.9
        assert rec["target_mastery"] == 0.2
        assert rec["edge_type"] == "reinforces"
        assert "Linear Algebra" in rec["recommendation"]
        assert "Matrix Transformations" in rec["recommendation"]

    @pytest.mark.asyncio
    async def test_same_course_edges_skipped(self):
        """Edges within the same course should be skipped."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        same_cid = uuid.uuid4()
        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[_make_mastery_mock(nid_a, 0.9), _make_mastery_mock(nid_b, 0.2)],
            node_mocks=[_make_node(nid_a, same_cid, "A"), _make_node(nid_b, same_cid, "B")],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_source_not_mastered_skipped(self):
        """If source concept is below mastery threshold, no recommendation produced."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[_make_mastery_mock(nid_a, 0.5), _make_mastery_mock(nid_b, 0.2)],
            node_mocks=[_make_node(nid_a, cid_a, "A"), _make_node(nid_b, cid_b, "B")],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_target_already_mastered_skipped(self):
        """If target concept is already at/above mastery threshold, no recommendation."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[_make_mastery_mock(nid_a, 0.9), _make_mastery_mock(nid_b, 0.8)],
            node_mocks=[_make_node(nid_a, cid_a, "A"), _make_node(nid_b, cid_b, "B")],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_results_sorted_by_target_mastery_ascending(self):
        """Recommendations should be sorted by target_mastery, lowest first."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        cid_a, cid_b, cid_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        nid_src, nid_t1, nid_t2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_src, nid_t1), _make_kg_edge(nid_src, nid_t2)],
            mastery_mocks=[
                _make_mastery_mock(nid_src, 0.9),
                _make_mastery_mock(nid_t1, 0.5),
                _make_mastery_mock(nid_t2, 0.1),
            ],
            node_mocks=[
                _make_node(nid_src, cid_a, "Source"),
                _make_node(nid_t1, cid_b, "Target High"),
                _make_node(nid_t2, cid_c, "Target Low"),
            ],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())

        assert len(result) == 2
        assert result[0]["target_mastery"] == 0.1
        assert result[1]["target_mastery"] == 0.5

    @pytest.mark.asyncio
    async def test_limit_capped_at_20(self):
        """Results should be capped at 20 recommendations."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        cid_src = uuid.uuid4()
        nid_src = uuid.uuid4()

        edges = []
        mastery_mocks = [_make_mastery_mock(nid_src, 0.95)]
        node_mocks = [_make_node(nid_src, cid_src, "Source")]

        for i in range(25):
            nid_tgt = uuid.uuid4()
            cid_tgt = uuid.uuid4()
            edges.append(_make_kg_edge(nid_src, nid_tgt))
            mastery_mocks.append(_make_mastery_mock(nid_tgt, 0.01 * i))
            node_mocks.append(_make_node(nid_tgt, cid_tgt, f"Target {i}"))

        db = self._setup_transfer_db(edges, mastery_mocks, node_mocks)
        result = await detect_transfer_opportunities(db, uuid.uuid4())
        assert len(result) == 20

    @pytest.mark.asyncio
    async def test_missing_node_in_node_map_skipped(self):
        """If a node referenced by an edge is missing from node_map, skip it."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[],
            node_mocks=[],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())
        assert result == []

    @pytest.mark.asyncio
    async def test_mastery_threshold_boundary_at_exactly_0_7(self):
        """Source at exactly 0.7 should count as mastered; target at 0.69 is a transfer opportunity."""
        from services.learning_science.transfer_detector import (
            MASTERY_THRESHOLD,
            detect_transfer_opportunities,
        )

        assert MASTERY_THRESHOLD == 0.7

        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[_make_mastery_mock(nid_a, 0.7), _make_mastery_mock(nid_b, 0.69)],
            node_mocks=[_make_node(nid_a, cid_a, "A"), _make_node(nid_b, cid_b, "B")],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())

        assert len(result) == 1
        assert result[0]["source_mastery"] == 0.7
        assert result[0]["target_mastery"] == 0.69

    @pytest.mark.asyncio
    async def test_no_mastery_data_defaults_to_zero(self):
        """Concepts with no mastery records should default to 0.0 mastery."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[_make_mastery_mock(nid_a, 0.85)],  # only source
            node_mocks=[_make_node(nid_a, cid_a, "A"), _make_node(nid_b, cid_b, "B")],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())

        assert len(result) == 1
        assert result[0]["target_mastery"] == 0.0

    @pytest.mark.asyncio
    async def test_recommendation_message_format(self):
        """Recommendation string should mention both source and target concept names."""
        from services.learning_science.transfer_detector import detect_transfer_opportunities

        cid_a, cid_b = uuid.uuid4(), uuid.uuid4()
        nid_a, nid_b = uuid.uuid4(), uuid.uuid4()

        db = self._setup_transfer_db(
            edges=[_make_kg_edge(nid_a, nid_b)],
            mastery_mocks=[_make_mastery_mock(nid_a, 0.9), _make_mastery_mock(nid_b, 0.1)],
            node_mocks=[_make_node(nid_a, cid_a, "Calculus"), _make_node(nid_b, cid_b, "Physics")],
        )
        result = await detect_transfer_opportunities(db, uuid.uuid4())

        assert len(result) == 1
        rec = result[0]["recommendation"]
        assert "Calculus" in rec
        assert "Physics" in rec
        assert "faster" in rec
