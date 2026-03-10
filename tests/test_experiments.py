"""Tests for services.experiments.framework and services.experiments.metrics."""

import math
import uuid

import pytest

from services.experiments.framework import (
    Experiment,
    ExperimentStatus,
    ExperimentVariant,
    register_experiment,
    get_experiment,
    list_experiments,
    get_user_variant,
    get_experiment_config,
    _experiments,
    _assignments,
)
from services.experiments.metrics import (
    _empty_metrics,
    _normal_cdf,
    two_proportion_z_test,
    mann_whitney_u,
)


# ── Framework: hash-based assignment ──


def test_deterministic_assignment():
    """Same user + experiment should always get the same variant."""
    exp = Experiment(
        id="test_det",
        name="Deterministic Test",
        description="test",
        variants=[
            ExperimentVariant(name="control", weight=0.5),
            ExperimentVariant(name="treatment", weight=0.5),
        ],
        status=ExperimentStatus.RUNNING,
    )
    uid = uuid.uuid4()
    v1 = exp.get_variant_for_user(uid)
    v2 = exp.get_variant_for_user(uid)
    assert v1.name == v2.name


def test_variant_distribution_roughly_fair():
    """With many users, both variants should get some users."""
    exp = Experiment(
        id="test_dist",
        name="Distribution Test",
        description="test",
        variants=[
            ExperimentVariant(name="a", weight=0.5),
            ExperimentVariant(name="b", weight=0.5),
        ],
    )
    counts = {"a": 0, "b": 0}
    for _ in range(200):
        v = exp.get_variant_for_user(uuid.uuid4())
        counts[v.name] += 1
    assert counts["a"] > 30
    assert counts["b"] > 30


def test_single_variant_always_selected():
    """An experiment with one variant should always return it."""
    exp = Experiment(
        id="test_single",
        name="Single",
        description="test",
        variants=[ExperimentVariant(name="only", weight=1.0)],
    )
    for _ in range(20):
        assert exp.get_variant_for_user(uuid.uuid4()).name == "only"


# ── Registry ──


def test_register_and_get_experiment():
    exp = Experiment(
        id="test_reg_" + uuid.uuid4().hex[:8],
        name="Reg Test",
        description="test",
        variants=[ExperimentVariant(name="c", weight=1.0)],
    )
    register_experiment(exp)
    assert get_experiment(exp.id) is exp


def test_get_user_variant_returns_none_for_non_running():
    """Non-RUNNING experiments should return None."""
    exp = Experiment(
        id="test_draft_" + uuid.uuid4().hex[:8],
        name="Draft",
        description="test",
        variants=[ExperimentVariant(name="c", weight=1.0)],
        status=ExperimentStatus.DRAFT,
    )
    register_experiment(exp)
    result = get_user_variant(uuid.uuid4(), exp.id)
    assert result is None


def test_get_experiment_config_returns_default():
    result = get_experiment_config(uuid.uuid4(), "nonexistent_experiment", "key", default=42)
    assert result == 42


# ── Metrics: _empty_metrics ──


def test_empty_metrics_all_zero():
    m = _empty_metrics()
    assert m["total_concepts"] == 0
    assert m["avg_mastery"] == 0.0
    assert m["accuracy"] == 0.0


# ── Metrics: _normal_cdf ──


def test_normal_cdf_symmetry():
    assert abs(_normal_cdf(0) - 0.5) < 1e-10
    assert abs(_normal_cdf(10) - 1.0) < 1e-6
    assert abs(_normal_cdf(-10) - 0.0) < 1e-6


# ── Metrics: two_proportion_z_test ──


def test_z_test_equal_proportions():
    """Same proportions should yield z=0, not significant."""
    result = two_proportion_z_test(50, 100, 50, 100)
    assert result["z_stat"] == 0.0
    assert result["significant"] is False


def test_z_test_very_different_proportions():
    """Very different proportions should be significant."""
    result = two_proportion_z_test(90, 100, 10, 100)
    assert result["significant"] is True
    assert result["effect_size"] > 0


def test_z_test_empty_group():
    """Empty group should return non-significant."""
    result = two_proportion_z_test(0, 0, 50, 100)
    assert result["significant"] is False
    assert result["p_value"] == 1.0


# ── Metrics: mann_whitney_u ──


def test_mann_whitney_identical_groups():
    """Identical groups should not be significant."""
    result = mann_whitney_u([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    assert result["significant"] is False


def test_mann_whitney_very_different_groups():
    """Clearly separated groups should be significant."""
    a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    b = [100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    result = mann_whitney_u(a, b)
    assert result["significant"] is True


def test_mann_whitney_empty_group():
    result = mann_whitney_u([], [1.0, 2.0])
    assert result["significant"] is False
    assert result["p_value"] == 1.0
