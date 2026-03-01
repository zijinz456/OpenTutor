"""A/B testing experiment API endpoints."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.user import User
from services.auth.dependency import get_current_user

router = APIRouter()


class CreateExperimentRequest(BaseModel):
    name: str
    dimension: str  # "prompt", "model", "strategy", "temperature"
    variants: list[dict]  # [{"id": "control", "config": {...}}, {"id": "treatment", "config": {...}}]
    description: str = ""
    traffic_fraction: float = Field(default=1.0, ge=0.0, le=1.0)
    primary_metric: str = "response_quality"


class RecordMetricRequest(BaseModel):
    experiment_id: str
    variant_id: str
    metric_name: str
    metric_value: float
    metadata: dict | None = None


@router.post("/")
async def create_experiment(
    body: CreateExperimentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new A/B test experiment."""
    from services.experiment.engine import create_experiment

    exp = await create_experiment(
        db, body.name, body.dimension, body.variants,
        body.description, body.traffic_fraction, body.primary_metric,
    )
    await db.commit()
    return {"id": str(exp.id), "name": exp.name, "status": "active"}


@router.get("/")
async def list_experiments(
    dimension: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List active experiments."""
    from services.experiment.engine import get_active_experiments

    experiments = await get_active_experiments(db, dimension)
    return [
        {
            "id": str(e.id),
            "name": e.name,
            "dimension": e.dimension,
            "is_active": e.is_active,
            "traffic_fraction": e.traffic_fraction,
            "variant_count": len(e.variants or []),
            "primary_metric": e.primary_metric,
        }
        for e in experiments
    ]


@router.get("/{experiment_id}/analyze")
async def analyze_experiment(
    experiment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Analyze experiment results with statistical significance testing."""
    from services.experiment.engine import analyze_experiment

    return await analyze_experiment(db, experiment_id)


@router.post("/{experiment_id}/end")
async def end_experiment(
    experiment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """End an experiment and get final analysis."""
    from services.experiment.engine import end_experiment

    result = await end_experiment(db, experiment_id)
    await db.commit()
    return result


@router.post("/record-metric")
async def record_metric(
    body: RecordMetricRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a metric event for an experiment."""
    from services.experiment.engine import record_metric

    await record_metric(
        db,
        uuid.UUID(body.experiment_id),
        user.id,
        body.variant_id,
        body.metric_name,
        body.metric_value,
        body.metadata,
    )
    await db.commit()
    return {"status": "recorded"}


@router.get("/my-variants")
async def get_my_variants(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all experiment variants assigned to the current user."""
    from sqlalchemy import select
    from models.experiment import ExperimentAssignment, Experiment

    result = await db.execute(
        select(ExperimentAssignment, Experiment)
        .join(Experiment, ExperimentAssignment.experiment_id == Experiment.id)
        .where(
            ExperimentAssignment.user_id == user.id,
            Experiment.is_active.is_(True),
        )
    )
    rows = result.all()
    return [
        {
            "experiment_id": str(a.experiment_id),
            "experiment_name": e.name,
            "dimension": e.dimension,
            "variant_id": a.variant_id,
        }
        for a, e in rows
    ]
