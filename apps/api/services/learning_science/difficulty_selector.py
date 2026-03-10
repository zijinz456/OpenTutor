"""Adaptive difficulty selection based on BKT mastery and gap type.

Maps student's current knowledge state to an optimal difficulty layer:
- P(L) < 0.4           → Layer 1 (fundamental / recall)
- 0.4 <= P(L) < 0.7    → Layer 2 (application / transfer)
- P(L) >= 0.7          → Layer 3 (traps / edge cases)

Gap type overrides:
- fundamental_gap       → Force Layer 1 regardless of mastery
- transfer_gap          → Force Layer 2 max
- trap_vulnerability    → Emphasise Layer 3

Reference: Vygotsky's Zone of Proximal Development — questions should be
just above the student's current ability to maximise learning.
"""

import uuid
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.progress import LearningProgress

logger = logging.getLogger(__name__)

# ZPD mastery thresholds for difficulty layer selection
MASTERY_LOW_THRESHOLD = 0.4     # Below this = Layer 1 (fundamental / recall)
MASTERY_HIGH_THRESHOLD = 0.7    # Above this = Layer 3 (traps / edge cases)

# Layer distribution presets (Layer 1, 2, 3 weights)
DIST_FUNDAMENTAL = {1: 0.7, 2: 0.3, 3: 0.0}
DIST_TRANSFER = {1: 0.2, 2: 0.6, 3: 0.2}
DIST_TRAP = {1: 0.1, 2: 0.3, 3: 0.6}
DIST_LOW_MASTERY = {1: 0.6, 2: 0.3, 3: 0.1}
DIST_MID_MASTERY = {1: 0.2, 2: 0.5, 3: 0.3}
DIST_HIGH_MASTERY = {1: 0.1, 2: 0.3, 3: 0.6}


@dataclass
class DifficultyRecommendation:
    """Recommended difficulty layer with rationale."""
    primary_layer: int           # 1, 2, or 3
    layer_distribution: dict     # e.g. {1: 0.2, 2: 0.5, 3: 0.3}
    rationale: str
    mastery_score: float
    gap_type: str | None


def recommend_difficulty(
    mastery_score: float,
    gap_type: str | None = None,
    fsrs_state: str | None = None,
) -> DifficultyRecommendation:
    """Recommend difficulty layer based on mastery and gap type.

    Returns a primary layer plus a distribution for generating mixed-difficulty sets.
    """
    # Gap type overrides
    if gap_type == "fundamental_gap":
        return DifficultyRecommendation(
            primary_layer=1,
            layer_distribution=DIST_FUNDAMENTAL,
            rationale="Fundamental gap detected — focus on core concept recall before progressing.",
            mastery_score=mastery_score,
            gap_type=gap_type,
        )

    if gap_type == "transfer_gap":
        return DifficultyRecommendation(
            primary_layer=2,
            layer_distribution=DIST_TRANSFER,
            rationale="Transfer gap — student knows the concept but struggles with application.",
            mastery_score=mastery_score,
            gap_type=gap_type,
        )

    if gap_type == "trap_vulnerability":
        return DifficultyRecommendation(
            primary_layer=3,
            layer_distribution=DIST_TRAP,
            rationale="Trap vulnerability — student understands well but falls for edge cases.",
            mastery_score=mastery_score,
            gap_type=gap_type,
        )

    # FSRS state: relearning cards should get easier questions
    if fsrs_state == "relearning":
        return DifficultyRecommendation(
            primary_layer=1,
            layer_distribution=DIST_LOW_MASTERY,
            rationale="Relearning state — reinforce fundamentals before advancing.",
            mastery_score=mastery_score,
            gap_type=gap_type,
        )

    # Mastery-based selection
    if mastery_score < MASTERY_LOW_THRESHOLD:
        return DifficultyRecommendation(
            primary_layer=1,
            layer_distribution=DIST_LOW_MASTERY,
            rationale=f"Low mastery ({mastery_score:.0%}) — build foundation first.",
            mastery_score=mastery_score,
            gap_type=gap_type,
        )

    if mastery_score < MASTERY_HIGH_THRESHOLD:
        return DifficultyRecommendation(
            primary_layer=2,
            layer_distribution=DIST_MID_MASTERY,
            rationale=f"Moderate mastery ({mastery_score:.0%}) — practice application and transfer.",
            mastery_score=mastery_score,
            gap_type=gap_type,
        )

    return DifficultyRecommendation(
        primary_layer=3,
        layer_distribution=DIST_HIGH_MASTERY,
        rationale=f"High mastery ({mastery_score:.0%}) — challenge with traps and edge cases.",
        mastery_score=mastery_score,
        gap_type=gap_type,
    )


async def get_recommendation_for_node(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    content_node_id: uuid.UUID | None = None,
) -> DifficultyRecommendation:
    """Get difficulty recommendation from database progress data."""
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
        return recommend_difficulty(0.0)

    return recommend_difficulty(
        mastery_score=progress.mastery_score,
        gap_type=progress.gap_type,
        fsrs_state=progress.fsrs_state,
    )


def format_for_prompt(rec: DifficultyRecommendation) -> str:
    """Format recommendation as text to inject into ExerciseAgent system prompt."""
    dist_str = ", ".join(f"Layer {k}: {v:.0%}" for k, v in sorted(rec.layer_distribution.items()))
    return (
        f"\n[ADAPTIVE DIFFICULTY GUIDANCE]\n"
        f"Recommended primary layer: {rec.primary_layer}\n"
        f"Distribution: {dist_str}\n"
        f"Rationale: {rec.rationale}\n"
        f"Note: This is a recommendation based on the student's knowledge state. "
        f"You may adjust if the student explicitly requests a different difficulty.\n"
    )
