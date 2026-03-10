"""System analytics endpoint — aggregated LOOM/LECTOR/cognitive-load metrics.

Provides a single endpoint that returns system-wide learning metrics:
- LOOM: graph density, concept coverage, avg mastery, Bloom distribution
- LECTOR: review completion, overdue counts, retention estimates
- Cognitive load: average load trend, intervention counts
- Experiments: active experiments, user assignments
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.course import Course
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery
from models.user import User
from services.auth.dependency import get_current_user
from services.course_access import get_course_or_404
from services.experiments.framework import list_experiments, ExperimentStatus
from services.experiments.metrics import compute_learning_metrics

logger = logging.getLogger(__name__)
router = APIRouter()


async def _loom_metrics(
    db: AsyncSession,
    course_id: uuid.UUID | None = None,
    owner_user_id: uuid.UUID | None = None,
) -> dict:
    """Compute LOOM knowledge graph metrics."""
    node_q = select(func.count()).select_from(KnowledgeNode)
    edge_q = select(func.count()).select_from(KnowledgeEdge)

    course_scope = None
    if course_id and owner_user_id:
        course_scope = select(Course.id).where(
            Course.id == course_id,
            Course.user_id == owner_user_id,
        )
    elif course_id:
        course_scope = select(Course.id).where(Course.id == course_id)
    elif owner_user_id:
        course_scope = select(Course.id).where(Course.user_id == owner_user_id)

    if course_scope is not None:
        node_q = node_q.where(KnowledgeNode.course_id.in_(course_scope))
        # Edges: filter by source node's course
        edge_q = edge_q.join(
            KnowledgeNode, KnowledgeEdge.source_id == KnowledgeNode.id
        ).where(KnowledgeNode.course_id.in_(course_scope))

    total_nodes = (await db.execute(node_q)).scalar() or 0
    total_edges = (await db.execute(edge_q)).scalar() or 0

    # Graph density = edges / (nodes * (nodes-1)) for directed graph
    density = 0.0
    if total_nodes > 1:
        density = total_edges / (total_nodes * (total_nodes - 1))

    # Edge type distribution
    type_q = (
        select(KnowledgeEdge.relation_type, func.count())
        .group_by(KnowledgeEdge.relation_type)
    )
    if course_scope is not None:
        type_q = type_q.join(
            KnowledgeNode, KnowledgeEdge.source_id == KnowledgeNode.id
        ).where(KnowledgeNode.course_id.in_(course_scope))

    type_result = await db.execute(type_q)
    edge_types = {row[0]: row[1] for row in type_result.all()}

    return {
        "total_concepts": total_nodes,
        "total_edges": total_edges,
        "graph_density": round(density, 4),
        "edge_types": edge_types,
    }


async def _lector_metrics(
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
) -> dict:
    """Compute LECTOR review system metrics."""
    now = datetime.now(timezone.utc)

    mastery_q = select(ConceptMastery)
    if user_id:
        mastery_q = mastery_q.where(ConceptMastery.user_id == user_id)
    if course_id:
        mastery_q = mastery_q.join(
            KnowledgeNode, ConceptMastery.knowledge_node_id == KnowledgeNode.id
        ).where(KnowledgeNode.course_id == course_id)

    result = await db.execute(mastery_q)
    masteries = result.scalars().all()

    if not masteries:
        return {
            "total_tracked": 0,
            "avg_mastery": 0.0,
            "mastered_count": 0,
            "overdue_count": 0,
            "avg_stability_days": 0.0,
            "avg_retention": 0.0,
            "total_practices": 0,
            "accuracy": 0.0,
        }

    total = len(masteries)
    avg_mastery = sum(m.mastery_score for m in masteries) / total
    mastered = sum(1 for m in masteries if m.mastery_score >= 0.8)
    overdue = sum(1 for m in masteries if m.next_review_at and m.next_review_at <= now)
    avg_stability = sum(m.stability_days for m in masteries) / total
    total_practices = sum(m.practice_count for m in masteries)
    total_correct = sum(m.correct_count for m in masteries)
    accuracy = total_correct / max(total_practices, 1)

    # FSRS retrievability estimate
    retention_vals = []
    for m in masteries:
        if m.last_practiced_at and m.stability_days > 0:
            days_since = (now - m.last_practiced_at).total_seconds() / 86400
            r = (1 + days_since / (9 * m.stability_days)) ** -1
            retention_vals.append(r)

    avg_retention = sum(retention_vals) / max(len(retention_vals), 1)

    return {
        "total_tracked": total,
        "avg_mastery": round(avg_mastery, 3),
        "mastered_count": mastered,
        "overdue_count": overdue,
        "avg_stability_days": round(avg_stability, 1),
        "avg_retention": round(avg_retention, 3),
        "total_practices": total_practices,
        "accuracy": round(accuracy, 3),
    }


def _experiment_summary() -> list[dict]:
    """Summarize registered experiments."""
    experiments = list_experiments()
    return [
        {
            "id": exp.id,
            "name": exp.name,
            "status": exp.status.value,
            "variants": len(exp.variants),
            "is_running": exp.status == ExperimentStatus.RUNNING,
        }
        for exp in experiments
    ]


@router.get("/analytics/system")
async def get_system_analytics(
    course_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated system analytics across LOOM, LECTOR, and experiments.

    Optional filters: course_id, user_id.
    """
    if user_id is not None and user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden: user_id does not match authenticated user")

    resolved_user_id = user_id or user.id
    if course_id is not None:
        await get_course_or_404(db, course_id, user_id=user.id)

    loom = await _loom_metrics(db, course_id=course_id, owner_user_id=user.id)
    lector = await _lector_metrics(db, resolved_user_id, course_id)
    experiments = _experiment_summary()

    # If user_id and course_id provided, also compute per-user learning metrics
    learning = None
    if resolved_user_id and course_id:
        learning = await compute_learning_metrics(db, resolved_user_id, course_id)

    return {
        "loom": loom,
        "lector": lector,
        "experiments": experiments,
        "learning_metrics": learning,
    }
