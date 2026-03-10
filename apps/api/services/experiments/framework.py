"""A/B Testing Framework for OpenTutor.

Provides feature flag system with user assignment to control/treatment groups.
Experiment variants can be defined for LECTOR scheduling strategies,
cognitive load thresholds, review session structure, etc.

Assignment is deterministic (hash-based) for consistency across sessions.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass
class ExperimentVariant:
    """A variant in an experiment."""
    name: str
    weight: float = 0.5  # Proportion of users assigned to this variant
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Experiment:
    """An A/B experiment definition."""
    id: str
    name: str
    description: str
    variants: list[ExperimentVariant]
    status: ExperimentStatus = ExperimentStatus.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_variant_for_user(self, user_id: uuid.UUID) -> ExperimentVariant:
        """Deterministically assign a user to a variant using hash-based bucketing."""
        hash_input = f"{self.id}:{user_id}".encode()
        hash_value = int(hashlib.sha256(hash_input).hexdigest(), 16)
        bucket = (hash_value % 1000) / 1000.0  # 0.0 - 1.0

        cumulative = 0.0
        for variant in self.variants:
            cumulative += variant.weight
            if bucket < cumulative:
                return variant

        return self.variants[-1]  # Fallback to last variant


# ── Global experiment registry ──

_experiments: dict[str, Experiment] = {}
_assignments: dict[str, dict[str, str]] = {}  # user_id -> {experiment_id -> variant_name}


def register_experiment(experiment: Experiment) -> None:
    """Register an experiment in the global registry."""
    _experiments[experiment.id] = experiment
    logger.info("Registered experiment: %s (%s)", experiment.name, experiment.id)


def get_experiment(experiment_id: str) -> Experiment | None:
    """Get an experiment by ID."""
    return _experiments.get(experiment_id)


def list_experiments() -> list[Experiment]:
    """List all registered experiments."""
    return list(_experiments.values())


def get_user_variant(
    user_id: uuid.UUID,
    experiment_id: str,
) -> ExperimentVariant | None:
    """Get the variant assigned to a user for a specific experiment."""
    experiment = _experiments.get(experiment_id)
    if not experiment or experiment.status != ExperimentStatus.RUNNING:
        return None

    # Check cached assignment
    user_key = str(user_id)
    if user_key in _assignments and experiment_id in _assignments[user_key]:
        variant_name = _assignments[user_key][experiment_id]
        for v in experiment.variants:
            if v.name == variant_name:
                return v

    # Assign variant
    variant = experiment.get_variant_for_user(user_id)

    # Cache assignment
    _assignments.setdefault(user_key, {})[experiment_id] = variant.name

    return variant


def get_experiment_config(
    user_id: uuid.UUID,
    experiment_id: str,
    config_key: str,
    default: Any = None,
) -> Any:
    """Get a specific config value from the user's assigned variant."""
    variant = get_user_variant(user_id, experiment_id)
    if variant is None:
        return default
    return variant.config.get(config_key, default)


# ── Built-in experiments ──

def _register_default_experiments() -> None:
    """Register default experiments for the learning science systems."""

    # Experiment 1: LECTOR scheduling strategy
    register_experiment(Experiment(
        id="lector_scheduling_v1",
        name="LECTOR Scheduling Strategy",
        description="Compare standard LECTOR scoring vs interleaved session structure",
        variants=[
            ExperimentVariant(
                name="control",
                weight=0.5,
                config={"use_structured_session": False},
            ),
            ExperimentVariant(
                name="treatment_interleaved",
                weight=0.5,
                config={"use_structured_session": True},
            ),
        ],
        status=ExperimentStatus.RUNNING,
    ))

    # Experiment 2: Cognitive load threshold
    register_experiment(Experiment(
        id="cognitive_load_threshold_v1",
        name="Cognitive Load Threshold",
        description="Test different thresholds for high cognitive load detection",
        variants=[
            ExperimentVariant(
                name="control",
                weight=0.5,
                config={"high_threshold": 0.6},
            ),
            ExperimentVariant(
                name="treatment_sensitive",
                weight=0.5,
                config={"high_threshold": 0.45},
            ),
        ],
        status=ExperimentStatus.RUNNING,
    ))

    # Experiment 3: FIRe propagation
    register_experiment(Experiment(
        id="fire_propagation_v1",
        name="FIRe Implicit Repetition",
        description="Test whether FIRe prerequisite propagation improves retention",
        variants=[
            ExperimentVariant(
                name="control",
                weight=0.5,
                config={"fire_enabled": False},
            ),
            ExperimentVariant(
                name="treatment_fire",
                weight=0.5,
                config={"fire_enabled": True},
            ),
        ],
        status=ExperimentStatus.RUNNING,
    ))


_register_default_experiments()
