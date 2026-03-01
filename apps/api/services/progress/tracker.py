"""Learning progress tracker service.

Tracks progress at course → chapter → knowledge point granularity.
Updates mastery scores based on quiz results and study time.

The mastery model uses recent-answer weighting plus layer-based gap inference:
- Recent answers weighted higher than old ones (0.95^i decay)
- Wrong answers weighted 1.3x vs correct answers 1.0x (asymmetric)
- Gap type inferred from difficulty-layer progression
"""

import uuid
import logging
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.progress import LearningProgress
from models.practice import PracticeResult, PracticeProblem
from models.content import CourseContentTree
from services.spaced_repetition.fsrs import FSRSCard, review_card
from services.learning_science.knowledge_tracer import compute_mastery_from_sequence

logger = logging.getLogger(__name__)

# Weighted decay constants for generic mastery tracking
_DECAY_FACTOR = 0.95       # Per-result recency decay
_WRONG_WEIGHT = 1.3        # Wrong answers count more than correct
_CORRECT_WEIGHT = 1.0      # Correct answer weight
_RECENT_RESULTS_LIMIT = 20 # How many recent results to consider


async def get_or_create_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
) -> LearningProgress:
    """Get or create a progress entry for a content node."""
    query = select(LearningProgress).where(
        LearningProgress.user_id == user_id,
        LearningProgress.course_id == course_id,
    )
    if content_node_id:
        query = query.where(LearningProgress.content_node_id == content_node_id)
    else:
        query = query.where(LearningProgress.content_node_id.is_(None))

    result = await db.execute(query)
    progress = result.scalar_one_or_none()

    if not progress:
        progress = LearningProgress(
            user_id=user_id,
            course_id=course_id,
            content_node_id=content_node_id,
        )
        db.add(progress)
        await db.flush()

    return progress


async def update_study_time(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
    minutes: int,
) -> LearningProgress:
    """Record study time for a content node."""
    progress = await get_or_create_progress(db, user_id, course_id, content_node_id)
    progress.time_spent_minutes += minutes
    progress.last_studied_at = datetime.utcnow()

    if progress.status == "not_started":
        progress.status = "in_progress"

    return progress


async def update_quiz_result(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
    is_correct: bool,
    error_category: str | None = None,
) -> LearningProgress:
    """Update progress based on quiz result.

    Uses weighted decay:
    - Recent results weighted higher (0.95^i decay)
    - Wrong answers weighted 1.3x vs correct 1.0x (asymmetric)
    - Gap type inferred from difficulty layer performance
    """
    progress = await get_or_create_progress(db, user_id, course_id, content_node_id)
    progress.quiz_attempts += 1
    if is_correct:
        progress.quiz_correct += 1

    # Mastery from two models: weighted decay + BKT probabilistic
    weighted_mastery = await _compute_weighted_mastery(db, user_id, course_id, content_node_id)
    bkt_mastery = await _compute_bkt_mastery(db, user_id, course_id, content_node_id)

    if weighted_mastery is not None and bkt_mastery is not None:
        # Blend: BKT (0.5) + weighted decay (0.2) + time (0.3)
        progress.mastery_score = (
            bkt_mastery * 0.5
            + weighted_mastery * 0.2
            + min(progress.time_spent_minutes / 60, 1.0) * 0.3
        )
    elif weighted_mastery is not None:
        progress.mastery_score = weighted_mastery * 0.7 + min(progress.time_spent_minutes / 60, 1.0) * 0.3
    elif bkt_mastery is not None:
        progress.mastery_score = bkt_mastery * 0.7 + min(progress.time_spent_minutes / 60, 1.0) * 0.3
    else:
        quiz_mastery = progress.quiz_correct / max(progress.quiz_attempts, 1)
        progress.mastery_score = quiz_mastery * 0.7 + min(progress.time_spent_minutes / 60, 1.0) * 0.3

    # Infer gap type from difficulty layer performance
    gap_type = await _infer_gap_type(db, user_id, course_id, content_node_id)
    if gap_type:
        progress.gap_type = gap_type

    # FSRS spaced repetition scheduling
    _apply_fsrs_review(progress, is_correct)

    # Update status
    if progress.mastery_score >= 0.8 and progress.quiz_attempts >= 3:
        progress.status = "mastered"
    elif progress.quiz_attempts > 0:
        progress.status = "reviewed"

    return progress


def _apply_fsrs_review(progress: LearningProgress, is_correct: bool) -> None:
    """Apply FSRS review to update spaced repetition fields.

    Maps quiz correctness to FSRS ratings:
    - Correct → 3 (Good)
    - Wrong   → 1 (Again)
    """
    card = FSRSCard(
        difficulty=progress.fsrs_difficulty,
        stability=progress.fsrs_stability,
        reps=progress.fsrs_reps,
        lapses=progress.fsrs_lapses,
        last_review=progress.last_studied_at,
        due=progress.next_review_at,
        state=progress.fsrs_state,
    )

    rating = 3 if is_correct else 1
    now = datetime.utcnow()
    updated_card, _log = review_card(card, rating, now)

    progress.fsrs_difficulty = updated_card.difficulty
    progress.fsrs_stability = updated_card.stability
    progress.fsrs_reps = updated_card.reps
    progress.fsrs_lapses = updated_card.lapses
    progress.fsrs_state = updated_card.state
    progress.next_review_at = updated_card.due
    progress.interval_days = max(1, round(updated_card.stability)) if updated_card.stability > 0 else 0
    progress.last_studied_at = now


async def _compute_weighted_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
) -> float | None:
    """Compute mastery using weighted decay over recent results.

    Recent results matter more (decay 0.95^i). Wrong answers are weighted
    heavier than correct ones (1.3x vs 1.0x) — asymmetric by design:
    a past mistake is not fully erased by a correct answer.
    """
    query = (
        select(PracticeResult)
        .join(PracticeProblem, PracticeResult.problem_id == PracticeProblem.id)
        .where(
            PracticeResult.user_id == user_id,
            PracticeProblem.course_id == course_id,
        )
        .order_by(PracticeResult.answered_at.desc())
        .limit(_RECENT_RESULTS_LIMIT)
    )
    if content_node_id:
        query = query.where(PracticeProblem.content_node_id == content_node_id)

    result = await db.execute(query)
    results = result.scalars().all()

    if not results:
        return None

    weighted_correct = 0.0
    total_weight = 0.0
    for i, pr in enumerate(results):
        decay = _DECAY_FACTOR ** i
        if pr.is_correct:
            w = _CORRECT_WEIGHT * decay
            weighted_correct += w
        else:
            w = _WRONG_WEIGHT * decay
        total_weight += w

    return weighted_correct / total_weight if total_weight > 0 else None


async def _compute_bkt_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
) -> float | None:
    """Compute mastery using Bayesian Knowledge Tracing over the answer sequence."""
    query = (
        select(PracticeResult.is_correct, PracticeProblem.question_type)
        .join(PracticeProblem, PracticeResult.problem_id == PracticeProblem.id)
        .where(
            PracticeResult.user_id == user_id,
            PracticeProblem.course_id == course_id,
        )
        .order_by(PracticeResult.answered_at.asc())
        .limit(_RECENT_RESULTS_LIMIT)
    )
    if content_node_id:
        query = query.where(PracticeProblem.content_node_id == content_node_id)

    result = await db.execute(query)
    rows = result.all()

    if not rows:
        return None

    results_seq = [bool(correct) for correct, _ in rows]
    # Use most common question type for parameter estimation
    q_types = [qt for _, qt in rows if qt]
    question_type = max(set(q_types), key=q_types.count) if q_types else None

    return compute_mastery_from_sequence(results_seq, question_type)


async def _infer_gap_type(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None,
) -> str | None:
    """Infer gap type from difficulty layer performance.

    Layer progression diagnosis:
    - Layer 1 fail -> fundamental_gap
    - Layer 1 pass, Layer 2 fail -> transfer_gap
    - Layer 2 pass, Layer 3 fail -> trap_vulnerability
    - All pass -> mastered

    Returns None if insufficient data (no layered questions attempted).
    """
    query = (
        select(
            PracticeProblem.difficulty_layer,
            PracticeResult.is_correct,
        )
        .join(PracticeProblem, PracticeResult.problem_id == PracticeProblem.id)
        .where(
            PracticeResult.user_id == user_id,
            PracticeProblem.course_id == course_id,
            PracticeProblem.difficulty_layer.isnot(None),
        )
    )
    if content_node_id:
        query = query.where(PracticeProblem.content_node_id == content_node_id)

    result = await db.execute(query)
    rows = result.all()

    if not rows:
        return None

    # Aggregate accuracy per layer
    layer_stats: dict[int, dict] = {}
    for layer, correct in rows:
        if layer not in layer_stats:
            layer_stats[layer] = {"attempts": 0, "correct": 0}
        layer_stats[layer]["attempts"] += 1
        if correct:
            layer_stats[layer]["correct"] += 1

    pass_threshold = 0.7

    def layer_passes(layer: int) -> bool | None:
        stats = layer_stats.get(layer)
        if not stats or stats["attempts"] < 2:
            return None  # Insufficient data
        return (stats["correct"] / stats["attempts"]) >= pass_threshold

    l1 = layer_passes(1)
    l2 = layer_passes(2)
    l3 = layer_passes(3)

    if l1 is False:
        return "fundamental_gap"
    if l1 is True and l2 is False:
        return "transfer_gap"
    if l2 is True and l3 is False:
        return "trap_vulnerability"
    if l1 is True and l2 is True and l3 is True:
        return "mastered"

    return None


async def get_course_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Get overall progress for a course."""
    # Get all content nodes for the course
    nodes_result = await db.execute(
        select(func.count(CourseContentTree.id))
        .where(CourseContentTree.course_id == course_id)
    )
    total_nodes = nodes_result.scalar() or 0

    # Get progress entries
    progress_result = await db.execute(
        select(LearningProgress)
        .where(
            LearningProgress.user_id == user_id,
            LearningProgress.course_id == course_id,
        )
    )
    progress_entries = progress_result.scalars().all()

    mastered = sum(1 for p in progress_entries if p.status == "mastered")
    reviewed = sum(1 for p in progress_entries if p.status == "reviewed")
    in_progress = sum(1 for p in progress_entries if p.status == "in_progress")
    total_time = sum(p.time_spent_minutes for p in progress_entries)
    avg_mastery = (
        sum(p.mastery_score for p in progress_entries) / len(progress_entries)
        if progress_entries else 0.0
    )
    gap_type_breakdown: dict[str, int] = {}
    for entry in progress_entries:
        if entry.gap_type:
            gap_type_breakdown[entry.gap_type] = gap_type_breakdown.get(entry.gap_type, 0) + 1

    return {
        "course_id": str(course_id),
        "total_nodes": total_nodes,
        "mastered": mastered,
        "reviewed": reviewed,
        "in_progress": in_progress,
        "not_started": max(0, total_nodes - mastered - reviewed - in_progress),
        "total_study_minutes": total_time,
        "average_mastery": avg_mastery,
        "completion_percent": (mastered + reviewed) / max(total_nodes, 1) * 100,
        "gap_type_breakdown": gap_type_breakdown,
    }
