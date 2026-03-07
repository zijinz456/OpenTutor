"""Progress tracking + learning template API endpoints."""

import uuid

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.course import Course
from models.ingestion import StudySession, WrongAnswer
from models.progress import LearningProgress
from models.practice import PracticeProblem
from models.user import User
from services.auth.dependency import get_current_user

router = APIRouter()


class ApplyTemplateRequest(BaseModel):
    template_id: uuid.UUID
    course_id: uuid.UUID | None = None


# ── Progress Endpoints ──


@router.get("/courses/{course_id}")
async def get_course_progress(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get learning progress overview for a course."""
    from services.progress.tracker import get_course_progress

    return await get_course_progress(db, user.id, course_id)


@router.get("/overview")
async def get_learning_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate cross-course learning analytics for the current user."""
    course_result = await db.execute(
        select(Course).where(Course.user_id == user.id).order_by(Course.created_at.desc())
    )
    courses = course_result.scalars().all()
    course_ids = [course.id for course in courses]
    if not course_ids:
        return {
            "total_courses": 0,
            "total_study_minutes": 0,
            "average_mastery": 0.0,
            "gap_type_breakdown": {},
            "diagnosis_breakdown": {},
            "error_category_breakdown": {},
            "course_summaries": [],
        }

    progress_result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user.id,
            LearningProgress.course_id.in_(course_ids),
        )
    )
    progress_rows = progress_result.scalars().all()

    wrong_result = await db.execute(
        select(WrongAnswer, PracticeProblem)
        .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
        .where(
            WrongAnswer.user_id == user.id,
            WrongAnswer.course_id.in_(course_ids),
        )
    )
    wrong_rows = wrong_result.all()

    session_result = await db.execute(
        select(StudySession).where(
            StudySession.user_id == user.id,
            StudySession.course_id.in_(course_ids),
        )
    )
    sessions = session_result.scalars().all()

    gap_type_breakdown: dict[str, int] = {}
    diagnosis_breakdown: dict[str, int] = {}
    error_category_breakdown: dict[str, int] = {}
    progress_by_course: dict[uuid.UUID, list[LearningProgress]] = {course_id: [] for course_id in course_ids}
    wrong_by_course: dict[uuid.UUID, list[WrongAnswer]] = {course_id: [] for course_id in course_ids}
    session_by_course: dict[uuid.UUID, list[StudySession]] = {course_id: [] for course_id in course_ids}

    for progress in progress_rows:
        progress_by_course.setdefault(progress.course_id, []).append(progress)
        if progress.gap_type:
            gap_type_breakdown[progress.gap_type] = gap_type_breakdown.get(progress.gap_type, 0) + 1

    for wrong_answer, _problem in wrong_rows:
        wrong_by_course.setdefault(wrong_answer.course_id, []).append(wrong_answer)
        if wrong_answer.diagnosis:
            diagnosis_breakdown[wrong_answer.diagnosis] = diagnosis_breakdown.get(wrong_answer.diagnosis, 0) + 1
        if wrong_answer.error_category:
            error_category_breakdown[wrong_answer.error_category] = error_category_breakdown.get(wrong_answer.error_category, 0) + 1

    for session in sessions:
        session_by_course.setdefault(session.course_id, []).append(session)

    course_summaries = []
    all_mastery_scores = [row.mastery_score for row in progress_rows]
    total_study_minutes = sum(session.duration_minutes or 0 for session in sessions)

    for course in courses:
        course_progress = progress_by_course.get(course.id, [])
        course_wrong = wrong_by_course.get(course.id, [])
        course_sessions = session_by_course.get(course.id, [])
        avg_mastery = (
            sum(item.mastery_score for item in course_progress) / len(course_progress)
            if course_progress else 0.0
        )
        course_summaries.append(
            {
                "course_id": str(course.id),
                "course_name": course.name,
                "average_mastery": avg_mastery,
                "study_minutes": sum(item.duration_minutes or 0 for item in course_sessions),
                "wrong_answers": len(course_wrong),
                "diagnosed_count": sum(1 for item in course_wrong if item.diagnosis),
                "gap_types": {
                    gap: sum(1 for item in course_progress if item.gap_type == gap)
                    for gap in {item.gap_type for item in course_progress if item.gap_type}
                },
            }
        )

    return {
        "total_courses": len(courses),
        "total_study_minutes": total_study_minutes,
        "average_mastery": (
            sum(all_mastery_scores) / len(all_mastery_scores) if all_mastery_scores else 0.0
        ),
        "gap_type_breakdown": gap_type_breakdown,
        "diagnosis_breakdown": diagnosis_breakdown,
        "error_category_breakdown": error_category_breakdown,
        "course_summaries": course_summaries,
    }


# ── Time-Series Analytics ──


@router.get("/courses/{course_id}/trends")
async def get_learning_trends(
    course_id: uuid.UUID,
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get daily learning trends for charts: mastery, study time, quiz accuracy."""
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Study sessions by day
    session_result = await db.execute(
        select(StudySession)
        .where(
            StudySession.user_id == user.id,
            StudySession.course_id == course_id,
            StudySession.started_at >= cutoff,
        )
        .order_by(StudySession.started_at)
    )
    sessions = session_result.scalars().all()

    # Progress snapshots — use updated_at to approximate daily mastery
    progress_result = await db.execute(
        select(LearningProgress)
        .where(
            LearningProgress.user_id == user.id,
            LearningProgress.course_id == course_id,
        )
    )
    progress_rows = progress_result.scalars().all()

    # Quiz results by day
    from models.practice import PracticeResult
    quiz_result = await db.execute(
        select(PracticeResult)
        .where(
            PracticeResult.user_id == user.id,
            PracticeResult.answered_at >= cutoff,
        )
        .order_by(PracticeResult.answered_at)
    )
    quiz_rows = quiz_result.scalars().all()

    # Build daily buckets
    daily: dict[str, dict] = {}
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily[d] = {"date": d, "study_minutes": 0, "quiz_total": 0, "quiz_correct": 0}

    for s in sessions:
        if s.started_at:
            d = s.started_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["study_minutes"] += s.duration_minutes or 0

    for q in quiz_rows:
        if q.answered_at:
            d = q.answered_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["quiz_total"] += 1
                if q.is_correct:
                    daily[d]["quiz_correct"] += 1

    # Compute running average mastery
    current_mastery = (
        sum(p.mastery_score for p in progress_rows) / len(progress_rows)
        if progress_rows else 0.0
    )

    trend_data = sorted(daily.values(), key=lambda x: x["date"])
    for entry in trend_data:
        entry["accuracy"] = (
            round(entry["quiz_correct"] / entry["quiz_total"] * 100, 1)
            if entry["quiz_total"] > 0 else None
        )

    return {
        "course_id": str(course_id),
        "days": days,
        "current_mastery": round(current_mastery * 100, 1),
        "trend": trend_data,
    }


@router.get("/trends")
async def get_global_trends(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get global daily learning trends across all courses."""
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    session_result = await db.execute(
        select(StudySession)
        .where(StudySession.user_id == user.id, StudySession.started_at >= cutoff)
        .order_by(StudySession.started_at)
    )
    sessions = session_result.scalars().all()

    from models.practice import PracticeResult
    quiz_result = await db.execute(
        select(PracticeResult)
        .where(PracticeResult.user_id == user.id, PracticeResult.answered_at >= cutoff)
        .order_by(PracticeResult.answered_at)
    )
    quiz_rows = quiz_result.scalars().all()

    daily: dict[str, dict] = {}
    for i in range(days):
        d = (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily[d] = {"date": d, "study_minutes": 0, "quiz_total": 0, "quiz_correct": 0}

    for s in sessions:
        if s.started_at:
            d = s.started_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["study_minutes"] += s.duration_minutes or 0

    for q in quiz_rows:
        if q.answered_at:
            d = q.answered_at.strftime("%Y-%m-%d")
            if d in daily:
                daily[d]["quiz_total"] += 1
                if q.is_correct:
                    daily[d]["quiz_correct"] += 1

    trend_data = sorted(daily.values(), key=lambda x: x["date"])
    for entry in trend_data:
        entry["accuracy"] = (
            round(entry["quiz_correct"] / entry["quiz_total"] * 100, 1)
            if entry["quiz_total"] > 0 else None
        )

    return {"days": days, "trend": trend_data}


# ── Weekly Report Endpoint ──


@router.get("/weekly-report")
async def get_weekly_report(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a weekly learning report with this-week vs last-week comparison."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    # Monday of this week
    this_monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    last_monday = this_monday - timedelta(days=7)

    async def _week_stats(start: datetime, end: datetime) -> dict:
        sess_result = await db.execute(
            select(StudySession).where(
                StudySession.user_id == user.id,
                StudySession.started_at >= start,
                StudySession.started_at < end,
            )
        )
        sessions = sess_result.scalars().all()
        study_minutes = sum(s.duration_minutes or 0 for s in sessions)
        active_days = len({s.started_at.strftime("%Y-%m-%d") for s in sessions if s.started_at})

        from models.practice import PracticeResult
        quiz_result = await db.execute(
            select(PracticeResult).where(
                PracticeResult.user_id == user.id,
                PracticeResult.answered_at >= start,
                PracticeResult.answered_at < end,
            )
        )
        quizzes = quiz_result.scalars().all()
        quiz_total = len(quizzes)
        quiz_correct = sum(1 for q in quizzes if q.is_correct)
        accuracy = round(quiz_correct / quiz_total * 100, 1) if quiz_total > 0 else 0.0

        return {
            "study_minutes": study_minutes,
            "active_days": active_days,
            "quiz_total": quiz_total,
            "quiz_correct": quiz_correct,
            "accuracy": accuracy,
        }

    this_week = await _week_stats(this_monday, now)
    last_week = await _week_stats(last_monday, this_monday)

    # Current mastery
    progress_result = await db.execute(
        select(LearningProgress).where(LearningProgress.user_id == user.id)
    )
    progress_rows = progress_result.scalars().all()
    mastery_avg = round(
        sum(p.mastery_score for p in progress_rows) / len(progress_rows) * 100, 1
    ) if progress_rows else 0.0

    # Deltas
    deltas = {
        "study_minutes": this_week["study_minutes"] - last_week["study_minutes"],
        "accuracy": round(this_week["accuracy"] - last_week["accuracy"], 1),
        "quiz_total": this_week["quiz_total"] - last_week["quiz_total"],
    }

    # Generate highlights
    highlights: list[str] = []
    if this_week["active_days"] >= 5:
        highlights.append(f"Studied {this_week['active_days']} days this week!")
    if deltas["accuracy"] > 0:
        highlights.append(f"Quiz accuracy improved by {deltas['accuracy']}%")
    if this_week["quiz_total"] > 0:
        highlights.append(f"Completed {this_week['quiz_total']} quiz questions")
    if this_week["study_minutes"] > 0:
        highlights.append(f"Studied for {this_week['study_minutes']} minutes total")
    if not highlights:
        highlights.append("Start studying to see your weekly progress!")

    return {
        "period": {
            "start": this_monday.strftime("%Y-%m-%d"),
            "end": now.strftime("%Y-%m-%d"),
        },
        "this_week": this_week,
        "last_week": last_week,
        "deltas": deltas,
        "mastery_avg": mastery_avg,
        "highlights": highlights[:4],
    }


# ── Memory Stats Endpoint ──


@router.get("/memory-stats")
async def get_memory_stats_endpoint(
    course_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get memory health statistics (type distribution, importance, consolidation status)."""
    from services.agent.memory_agent import get_memory_stats

    return await get_memory_stats(db, user.id, course_id)


@router.post("/memory-consolidate")
async def trigger_consolidation(
    course_id: uuid.UUID | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger memory consolidation (dedup + decay + categorize + merge)."""
    from services.agent.memory_agent import run_full_consolidation

    result = await run_full_consolidation(db, user.id, course_id)
    return result


# ── Template Endpoints ──


@router.get("/templates")
async def list_templates(db: AsyncSession = Depends(get_db)):
    """List all available learning templates."""
    from services.templates.system import list_templates

    return await list_templates(db)


@router.post("/templates/apply")
async def apply_template(
    body: ApplyTemplateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply a learning template to the user's preferences."""
    from services.templates.system import apply_template

    result = await apply_template(db, user.id, body.template_id, body.course_id)
    await db.commit()
    return result


@router.post("/templates/seed")
async def seed_templates(db: AsyncSession = Depends(get_db)):
    """Seed built-in learning templates (run once on setup)."""
    from services.templates.system import seed_builtin_templates

    count = await seed_builtin_templates(db)
    await db.commit()
    return {"seeded": count}


# ── Forgetting Forecast Endpoint ──


@router.get("/courses/{course_id}/forgetting-forecast")
async def get_forgetting_forecast(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Predict when each knowledge point will be forgotten (FSRS retrievability)."""
    from services.spaced_repetition.forgetting_forecast import predict_forgetting

    return await predict_forgetting(db, user.id, course_id)


# ── Knowledge Graph Endpoint ──


@router.get("/courses/{course_id}/knowledge-graph")
async def get_knowledge_graph(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph for a course (D3-compatible format)."""
    try:
        from services.knowledge.graph import build_knowledge_graph
        return await build_knowledge_graph(db, course_id, user.id)
    except ImportError:
        return {"nodes": [], "edges": [], "course_id": str(course_id)}


# ── Learning Path Optimization Endpoint ──


@router.get("/courses/{course_id}/learning-path")
async def get_learning_path(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get recommended learning path based on prerequisite topology and mastery gaps.

    Returns knowledge-point nodes sorted by recommended order:
    - Nodes with unmet prerequisites first (topological sort)
    - Within same level, low-mastery nodes prioritised
    - Each node annotated with a recommended_reason
    """
    from services.knowledge.graph_memory import get_learning_path_recommendations

    recommendations = await get_learning_path_recommendations(db, user.id, course_id)
    return {"course_id": str(course_id), "recommendations": recommendations}


@router.get("/courses/{course_id}/misconceptions")
async def get_misconception_dashboard(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get misconception dashboard: things you think you understand but don't.

    Aggregates WrongAnswer diagnosis, LearningProgress gap types, and
    comprehension probe results into a prioritized list of misconceptions
    ranked by exam relevance and recency.
    """
    from datetime import datetime, timezone
    from models.practice import PracticeResult

    # 1. Wrong answers with diagnosis (unmastered = active misconceptions)
    wrong_result = await db.execute(
        select(WrongAnswer, PracticeProblem)
        .join(PracticeProblem, WrongAnswer.problem_id == PracticeProblem.id)
        .where(
            WrongAnswer.course_id == course_id,
            WrongAnswer.user_id == user.id,
        )
        .order_by(WrongAnswer.created_at.desc())
    )
    wrong_rows = wrong_result.all()

    # 2. Learning progress with gap types
    progress_result = await db.execute(
        select(LearningProgress).where(
            LearningProgress.user_id == user.id,
            LearningProgress.course_id == course_id,
            LearningProgress.gap_type.isnot(None),
            LearningProgress.gap_type != "mastered",
        )
    )
    gap_rows = progress_result.scalars().all()

    # 3. Group wrong answers by core concept
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

        # Track latest error time
        if wa.created_at:
            if entry["latest_error_at"] is None or wa.created_at > entry["latest_error_at"]:
                entry["latest_error_at"] = wa.created_at

        # Collect sample questions (max 3)
        if len(entry["sample_questions"]) < 3:
            entry["sample_questions"].append({
                "question": prob.question[:200] if prob.question else "",
                "user_answer": wa.user_answer[:100] if wa.user_answer else "",
                "correct_answer": wa.correct_answer[:100] if wa.correct_answer else "",
                "error_category": wa.error_category,
                "diagnosis": wa.diagnosis,
            })

        # Collect misconception types from comprehension probes
        detail = wa.error_detail or {}
        if detail.get("misconception_type"):
            entry["misconception_types"].append(detail["misconception_type"])

    # 4. Enrich with comprehension probe data from LearningProgress metadata
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

    # 5. Build ranked misconception list
    now = datetime.now(timezone.utc)
    misconceptions = []
    for key, entry in concept_map.items():
        active_errors = entry["total_errors"] - entry["mastered_errors"]
        if active_errors <= 0 and not entry["misconception_types"]:
            continue  # Skip fully mastered concepts

        # Priority score: more active errors + more recent = higher priority
        recency_days = 999
        if entry["latest_error_at"]:
            try:
                delta = now - entry["latest_error_at"]
                recency_days = max(delta.days, 0)
            except TypeError:
                pass
        recency_boost = max(0, 30 - recency_days) / 30  # 1.0 if today, 0.0 if 30+ days ago

        # Dominant diagnosis
        diagnoses = entry["diagnoses"]
        dominant_diagnosis = max(diagnoses, key=diagnoses.get) if diagnoses else None

        # Dominant misconception type from probes
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

    # Sort by priority (highest first)
    misconceptions.sort(key=lambda x: x["priority_score"], reverse=True)

    # 6. Summary stats
    total_active = sum(m["active_errors"] for m in misconceptions)
    total_resolved = sum(m["mastered_errors"] for m in misconceptions)

    diagnosis_summary: dict[str, int] = {}
    for m in misconceptions:
        if m["dominant_diagnosis"]:
            d = m["dominant_diagnosis"]
            diagnosis_summary[d] = diagnosis_summary.get(d, 0) + 1

    return {
        "course_id": str(course_id),
        "misconceptions": misconceptions[:20],  # Top 20
        "summary": {
            "total_concepts_with_issues": len(misconceptions),
            "total_active_errors": total_active,
            "total_resolved": total_resolved,
            "resolution_rate": round(
                total_resolved / max(total_active + total_resolved, 1) * 100, 1
            ),
            "diagnosis_breakdown": diagnosis_summary,
        },
    }


@router.get("/courses/{course_id}/knowledge-graph-mastery")
async def get_knowledge_graph_mastery(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge graph nodes coloured by mastery status.

    Mastery colouring:
    - mastered (green):  mastery >= 0.8
    - developing (yellow): mastery >= 0.5
    - weak (red):        mastery < 0.5
    - unknown (gray):    no mastery data
    """
    from services.knowledge.graph_memory import get_mastery_colored_graph

    nodes = await get_mastery_colored_graph(db, user.id, course_id)
    return {"course_id": str(course_id), "nodes": nodes}


@router.get("/courses/{course_id}/review-session")
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


@router.post("/courses/{course_id}/review-session/rate")
async def submit_review_rating(
    course_id: uuid.UUID,
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a rating for a reviewed concept (again/hard/good/easy).

    Updates ConceptMastery with new mastery score, stability, and review timestamp.
    Body: { "concept_id": str, "rating": "again"|"hard"|"good"|"easy" }
    """
    from models.knowledge_graph import ConceptMastery

    concept_id = body.get("concept_id")
    rating = body.get("rating", "good")
    if not concept_id:
        raise HTTPException(status_code=400, detail="concept_id is required")

    # Rating → mastery adjustment factors
    RATING_FACTORS = {
        "again": {"mastery_delta": -0.15, "stability_mult": 0.3, "correct": False},
        "hard":  {"mastery_delta": -0.05, "stability_mult": 0.7, "correct": True},
        "good":  {"mastery_delta": 0.05,  "stability_mult": 1.5, "correct": True},
        "easy":  {"mastery_delta": 0.10,  "stability_mult": 2.5, "correct": True},
    }
    factors = RATING_FACTORS.get(rating, RATING_FACTORS["good"])

    try:
        concept_uuid = uuid.UUID(concept_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid concept_id")

    # Find or create mastery record
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
        # Schedule next review based on stability
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


@router.get("/courses/{course_id}/loom")
async def get_loom_graph(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get LOOM concept mastery graph with nodes, edges, and recommendations."""
    from services.loom import get_mastery_graph

    graph = await get_mastery_graph(db, user.id, course_id)
    return {"course_id": str(course_id), **graph}


@router.get("/courses/{course_id}/learning-path")
async def get_learning_path(
    course_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get prerequisite-respecting study order for unmastered concepts (Kahn's algorithm)."""
    from services.loom import generate_learning_path

    path = await generate_learning_path(db, course_id, user.id)
    return {"course_id": str(course_id), "path": path, "count": len(path)}
