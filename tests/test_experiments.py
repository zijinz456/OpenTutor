"""Tests for services.experiments.framework."""

import uuid

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
