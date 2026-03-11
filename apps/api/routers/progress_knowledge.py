"""Progress knowledge endpoints — knowledge graph, LOOM, learning path, review, velocity."""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from libs.exceptions import KnowledgeGraphUnavailableError
from models.ingestion import WrongAnswer
from models.progress import LearningProgress
from models.practice import PracticeProblem
from models.user import User
from services.auth.dependency import get_current_user
from services.knowledge.graph import build_knowledge_graph

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Forgetting Forecast ──


@router.get("/courses/{course_id}/forgetting-forecast", summary="Get forgetting forecast", description="Predict when each knowledge point will be forgotten using FSRS retrievability.")
async def get_forgetting_forecast(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Predict when each knowledge point will be forgotten (FSRS retrievability)."""
    from services.spaced_repetition.forgetting_forecast import predict_forgetting

    return await predict_forgetting(db, user.id, course_id)


# ── Knowledge Graph ──


@router.get("/courses/{course_id}/knowledge-graph", summary="Get knowledge graph", description="Return the knowledge graph for a course in D3-compatible format.")
async def get_knowledge_graph(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph for a course (D3-compatible format)."""
    try:
        return await build_knowledge_graph(db, course_id, user.id)
    except KnowledgeGraphUnavailableError:
        raise
    except (SQLAlchemyError, KeyError, ValueError, TypeError, RuntimeError) as exc:
        logger.exception("Knowledge graph build failed for course %s user %s", course_id, user.id)
        raise KnowledgeGraphUnavailableError() from exc


@router.get("/courses/{course_id}/knowledge-graph-mastery", summary="Get mastery-colored graph", description="Return knowledge graph nodes colored by mastery status.")
async def get_knowledge_graph_mastery(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph nodes coloured by mastery status."""
    from services.knowledge.graph_memory import get_mastery_colored_graph

    nodes = await get_mastery_colored_graph(db, user.id, course_id)
    return {"course_id": str(course_id), "nodes": nodes}


# ── Learning Path ──


@router.get("/courses/{course_id}/learning-path", summary="Get learning path", description="Return prerequisite-respecting study order for unmastered concepts.")
async def get_learning_path(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get prerequisite-respecting study order for unmastered concepts (Kahn's algorithm)."""
    from services.loom import generate_learning_path

    path = await generate_learning_path(db, course_id, user.id)
    return {"course_id": str(course_id), "path": path, "count": len(path)}


# ── Misconceptions ──


@router.get("/courses/{course_id}/misconceptions", summary="Get misconception dashboard", description="Return misconceptions grouped by concept with error analysis and priority scores.")
async def get_misconception_dashboard(
    course_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get misconception dashboard: things you think you understand but don't."""
    wrong_result = await db.execute(
        select(WrongAnswer, PracticeProblem)
        .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
        .where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
        )
        .order_by(WrongAnswer.created_at.desc())
        .limit(500)  # Cap to prevent unbounded data load
    )
    wrong_rows = wrong_result.all()

    progress_result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user.id,
            LearningProgress.course_id == course_id,
            LearningProgress.gap_type.isnot(None),
            LearningProgress.gap_type != "mastered",
        )
    )
    gap_rows = progress_result.scalars().all()

    concept_map: dict[str, dict] = {}
    for wa, prob in wrong_rows:
        metadata = prob.problem_metadata or {}
        concept = metadata.get("core_concept") or metadata.get("topic") or "Unknown"
        key = concept.lower().strip()

        if key not in concept_map:
            concept_map[key] = {
                "concept": concept,
                "total_errors": 0,
                "mastered_errors": 0,
                "error_categories": {},
                "diagnoses": {},
                "latest_error_at": None,
                "sample_questions": [],
                "misconception_types": [],
            }

        entry = concept_map[key]
        entry["total_errors"] += 1
        if wa.mastered:
            entry["mastered_errors"] += 1

        cat = wa.error_category or "uncategorized"
        entry["error_categories"][cat] = entry["error_categories"].get(cat, 0) + 1

        if wa.diagnosis:
            entry["diagnoses"][wa.diagnosis] = entry["diagnoses"].get(wa.diagnosis, 0) + 1

        if wa.created_at:
            if entry["latest_error_at"] is None or wa.created_at > entry["latest_error_at"]:
                entry["latest_error_at"] = wa.created_at

        if len(entry["sample_questions"]) < 3:
            entry["sample_questions"].append({
                "question": prob.question[:200] if prob.question else "",
                "user_answer": wa.user_answer[:100] if wa.user_answer else "",
                "correct_answer": wa.correct_answer[:100] if wa.correct_answer else "",
                "error_category": wa.error_category,
                "diagnosis": wa.diagnosis,
            })

        detail = wa.error_detail or {}
        if detail.get("misconception_type"):
            entry["misconception_types"].append(detail["misconception_type"])

    for prog in gap_rows:
        meta = prog.metadata_json or {}
        probes = meta.get("comprehension_probes") or []
        for probe in probes:
            if not probe.get("understood") and probe.get("concept"):
                key = probe["concept"].lower().strip()
                if key not in concept_map:
                    concept_map[key] = {
                        "concept": probe["concept"],
                        "total_errors": 0,
                        "mastered_errors": 0,
                        "error_categories": {},
                        "diagnoses": {},
                        "latest_error_at": None,
                        "sample_questions": [],
                        "misconception_types": [],
                    }
                mt = probe.get("misconception_type")
                if mt:
                    concept_map[key]["misconception_types"].append(mt)

    now = datetime.now(timezone.utc)
    misconceptions = []
    for key, entry in concept_map.items():
        active_errors = entry["total_errors"] - entry["mastered_errors"]
        if active_errors <= 0 and not entry["misconception_types"]:
            continue

        recency_days = 999
        if entry["latest_error_at"]:
            try:
                delta = now - entry["latest_error_at"]
                recency_days = max(delta.days, 0)
            except TypeError as exc:
                logger.debug("Failed to compute recency for concept '%s': %s", key, exc)
        recency_boost = max(0, 30 - recency_days) / 30

        diagnoses = entry["diagnoses"]
        dominant_diagnosis = max(diagnoses, key=diagnoses.get) if diagnoses else None

        mt_list = entry["misconception_types"]
        dominant_misconception = max(set(mt_list), key=mt_list.count) if mt_list else None

        priority_score = round(active_errors * 0.6 + recency_boost * 0.4, 2)

        misconceptions.append({
            "concept": entry["concept"],
            "active_errors": active_errors,
            "total_errors": entry["total_errors"],
            "mastered_errors": entry["mastered_errors"],
            "resolution_rate": round(
                entry["mastered_errors"] / max(entry["total_errors"], 1) * 100, 1
            ),
            "dominant_diagnosis": dominant_diagnosis,
            "dominant_misconception_type": dominant_misconception,
            "error_categories": entry["error_categories"],
            "priority_score": priority_score,
            "sample_questions": entry["sample_questions"],
        })

    misconceptions.sort(key=lambda x: x["priority_score"], reverse=True)

    total_active = sum(m["active_errors"] for m in misconceptions)
    total_resolved = sum(m["mastered_errors"] for m in misconceptions)

    diagnosis_summary: dict[str, int] = {}
    for m in misconceptions:
        if m["dominant_diagnosis"]:
            d = m["dominant_diagnosis"]
            diagnosis_summary[d] = diagnosis_summary.get(d, 0) + 1

    total_count = len(misconceptions)
    page = misconceptions[offset : offset + limit]

    return {
        "course_id": str(course_id),
        "misconceptions": page,
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "summary": {
            "total_concepts_with_issues": total_count,
            "total_active_errors": total_active,
            "total_resolved": total_resolved,
            "resolution_rate": round(
                total_resolved / max(total_active + total_resolved, 1) * 100, 1
            ),
            "diagnosis_breakdown": diagnosis_summary,
        },
    }


# ── Review Session ──


@router.get("/courses/{course_id}/review-session", summary="Get smart review session", description="Return a LECTOR-ordered review session with semantically clustered concepts.")
async def get_review_session(
    course_id: uuid.UUID,
    max_items: int = 10,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get LECTOR smart review session — semantically clustered concepts to review."""
    from services.lector import get_smart_review_session
    from dataclasses import asdict

    items = await get_smart_review_session(db, user.id, course_id, max_items=max_items)
    return {
        "course_id": str(course_id),
        "items": [asdict(i) for i in items],
        "count": len(items),
    }


class ReviewRatingRequest(BaseModel):
    concept_id: uuid.UUID
    rating: str = "good"


@router.post("/courses/{course_id}/review-session/rate", summary="Rate a reviewed concept", description="Submit a rating for a reviewed concept and update mastery scheduling.")
async def submit_review_rating(
    course_id: uuid.UUID,
    body: ReviewRatingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a rating for a reviewed concept (again/hard/good/easy)."""
    from models.knowledge_graph import ConceptMastery

    concept_id = str(body.concept_id)
    rating = body.rating

    RATING_FACTORS = {
        "again": {"mastery_delta": -0.15, "stability_mult": 0.3, "correct": False},
        "hard":  {"mastery_delta": -0.05, "stability_mult": 0.7, "correct": True},
        "good":  {"mastery_delta": 0.05,  "stability_mult": 1.5, "correct": True},
        "easy":  {"mastery_delta": 0.10,  "stability_mult": 2.5, "correct": True},
    }
    if rating not in RATING_FACTORS:
        raise HTTPException(status_code=400, detail=f"Invalid rating '{rating}'. Must be one of: again, hard, good, easy")
    factors = RATING_FACTORS[rating]

    concept_uuid = body.concept_id

    result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user.id,
            ConceptMastery.knowledge_node_id == concept_uuid,
        )
    )
    mastery = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if not mastery:
        mastery = ConceptMastery(
            user_id=user.id,
            knowledge_node_id=concept_uuid,
            mastery_score=max(0.0, min(1.0, 0.3 + factors["mastery_delta"])),
            practice_count=1,
            correct_count=1 if factors["correct"] else 0,
            wrong_count=0 if factors["correct"] else 1,
            last_practiced_at=now,
            stability_days=max(0.5, 1.0 * factors["stability_mult"]),
        )
        db.add(mastery)
    else:
        mastery.mastery_score = max(0.0, min(1.0, mastery.mastery_score + factors["mastery_delta"]))
        mastery.practice_count += 1
        if factors["correct"]:
            mastery.correct_count += 1
        else:
            mastery.wrong_count += 1
        mastery.stability_days = max(0.5, mastery.stability_days * factors["stability_mult"])
        mastery.last_practiced_at = now
        from datetime import timedelta
        mastery.next_review_at = now + timedelta(days=mastery.stability_days)

    await db.commit()

    return {
        "concept_id": concept_id,
        "rating": rating,
        "new_mastery": round(mastery.mastery_score, 3),
        "new_stability_days": round(mastery.stability_days, 1),
        "next_review_at": mastery.next_review_at.isoformat() if mastery.next_review_at else None,
    }


# ── LOOM ──


@router.get("/courses/{course_id}/loom", summary="Get LOOM mastery graph", description="Return LOOM concept mastery graph with nodes, edges, and recommendations.")
async def get_loom_graph(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get LOOM concept mastery graph with nodes, edges, and recommendations."""
    from services.loom import get_mastery_graph

    graph = await get_mastery_graph(db, user.id, course_id)
    return {"course_id": str(course_id), **graph}


# ── Velocity & Forecast ──


@router.get("/courses/{course_id}/velocity", summary="Get learning velocity", description="Return learning velocity statistics for a course over a time window.")
async def get_learning_velocity(
    course_id: uuid.UUID,
    window_days: int = 7,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get learning velocity stats for a course."""
    from services.learning_science.velocity_tracker import compute_velocity

    return await compute_velocity(db, course_id, window_days=window_days)


@router.get("/courses/{course_id}/forecast", summary="Get completion forecast", description="Forecast course completion date based on current learning velocity.")
async def get_completion_forecast(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Forecast course completion date based on learning velocity."""
    from services.learning_science.completion_forecaster import forecast_completion

    return await forecast_completion(db, course_id)


@router.get("/transfer-opportunities", summary="Get transfer opportunities", description="Detect cross-course transfer learning opportunities.")
async def get_transfer_opportunities(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detect cross-course transfer learning opportunities."""
    from services.learning_science.transfer_detector import detect_transfer_opportunities

    return await detect_transfer_opportunities(db, user.id)
