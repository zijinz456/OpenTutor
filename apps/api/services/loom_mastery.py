"""LOOM mastery — concept mastery tracking, BKT updates, and bidirectional FIRe propagation.

Handles updating mastery scores after practice/quiz attempts and
propagating fractional implicit repetition credit to prerequisites.

Academic foundations:
- BKT (Bayesian Knowledge Tracing): question-type-aware guess/slip for mastery updates (pyBKT)
- GKT (Graph-based Knowledge Tracing): bidirectional mastery propagation through KG edges
- FIRe: Fractional Implicit Repetitions in Knowledge Graphs (2024)
- LOOM: Concept consolidation when prerequisite groups reach mastery (arXiv 2511.21037)
"""

import logging
import uuid
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery

logger = logging.getLogger(__name__)

# ── BKT Parameters (pyBKT paper) ──
# Question-type-specific guess/slip parameters: (guess_probability, slip_probability)
# guess = P(correct | not learned), slip = P(incorrect | learned)
BKT_PARAMS: dict[str, tuple[float, float]] = {
    "mc": (0.25, 0.10),            # MCQ: 25% chance of guessing correctly (1/4 options)
    "tf": (0.50, 0.10),            # True/False: 50% chance of guessing
    "short_answer": (0.05, 0.10),  # Short answer: very low guess probability
    "free_response": (0.05, 0.10), # Free response: very low guess probability
    "fill_blank": (0.10, 0.10),    # Fill-in-blank: low guess probability
    "matching": (0.15, 0.10),      # Matching: moderate guess probability
    "select_all": (0.10, 0.10),    # Select all: low guess probability
}
BKT_DEFAULT_PARAMS = (0.15, 0.10)  # Default: moderate guess
BKT_P_LEARN = 0.10                 # Learning transition probability per practice

# ── FIRe Parameters ──
FIRE_BOOST_PER_DEPTH = 0.05   # 5% mastery boost per FIRe propagation level (correct)
FIRE_DOUBT_PER_DEPTH = 0.03   # 3% mastery reduction per depth level (incorrect, GKT-inspired)

# ── Consolidation Parameters (LOOM paper) ──
CONSOLIDATION_THRESHOLD = 0.85          # All prereqs must exceed this mastery
CONSOLIDATION_PARENT_BOOST = 0.1        # Mastery boost for parent concept
CONSOLIDATION_STABILITY_MULTIPLIER = 1.5  # Extend review interval for mastered prereqs


# ── BKT Mastery Update ──

def _bkt_update(prior: float, correct: bool, question_type: str | None = None) -> float:
    """Bayesian Knowledge Tracing mastery update with question-type-aware guess/slip.

    Based on pyBKT (CAHLR, 242★ on GitHub):
    P(L|correct) = P(L)·(1-slip) / [P(L)·(1-slip) + (1-P(L))·guess]
    P(L|incorrect) = P(L)·slip / [P(L)·slip + (1-P(L))·(1-guess)]
    P(L_next) = P(L|obs) + (1 - P(L|obs)) · p_learn

    Key insight: MCQ correct barely moves mastery (could be guessing),
    while free-response correct gives strong evidence of learning.
    """
    guess, slip = BKT_PARAMS.get(question_type or "", BKT_DEFAULT_PARAMS)
    prior = max(0.001, min(0.999, prior))  # Avoid division by zero

    if correct:
        # P(Learned | Correct) = P(L)·(1-slip) / [P(L)·(1-slip) + (1-P(L))·guess]
        posterior = prior * (1 - slip) / (prior * (1 - slip) + (1 - prior) * guess)
    else:
        # P(Learned | Incorrect) = P(L)·slip / [P(L)·slip + (1-P(L))·(1-guess)]
        posterior = prior * slip / (prior * slip + (1 - prior) * (1 - guess))

    # Learning transition: even after observing, there's a chance the student learned
    updated = posterior + (1 - posterior) * BKT_P_LEARN
    return max(0.0, min(1.0, updated))


# ── Mastery Tracking ──

async def update_concept_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    concept_name: str,
    course_id: uuid.UUID,
    correct: bool,
    question_type: str | None = None,
) -> ConceptMastery | None:
    """Update mastery score for a concept after practice/quiz.

    Uses BKT Bayesian update with question-type-aware guess/slip parameters
    instead of simple EMA. This means:
    - MCQ correct (guess=0.25) barely increases mastery for low-mastery students
    - Free-response correct (guess=0.05) strongly increases mastery
    - Incorrect on T/F (slip=0.10) doesn't overly punish high-mastery students
    """
    # Find the concept node
    result = await db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.course_id == course_id,
            func.lower(KnowledgeNode.name) == concept_name.lower(),
        )
    )
    node = result.scalar_one_or_none()
    if not node:
        return None

    # Get or create mastery record
    result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id == node.id,
        )
    )
    mastery = result.scalar_one_or_none()

    if not mastery:
        mastery = ConceptMastery(
            user_id=user_id,
            knowledge_node_id=node.id,
            mastery_score=0.0,
            practice_count=0,
            correct_count=0,
            wrong_count=0,
            stability_days=1.0,
        )
        db.add(mastery)

    # Update counters
    mastery.practice_count += 1
    if correct:
        mastery.correct_count += 1
    else:
        mastery.wrong_count += 1

    # BKT Bayesian mastery update (replaces EMA)
    mastery.mastery_score = _bkt_update(mastery.mastery_score, correct, question_type)

    # FSRS-based stability and scheduling
    from services.spaced_repetition.fsrs import FSRSCard, review_card as fsrs_review

    fsrs_card = FSRSCard(
        difficulty=5.0,
        stability=mastery.stability_days if mastery.stability_days > 0 else 1.0,
        reps=mastery.practice_count - 1,  # -1 because we already incremented
        lapses=mastery.wrong_count,
        last_review=mastery.last_practiced_at,
        state="review" if mastery.practice_count > 1 else "new",
    )

    # Map correct/incorrect to FSRS ratings
    if correct:
        rating = 3  # Good
    else:
        rating = 1  # Again

    now = datetime.now(timezone.utc)
    updated_card, _ = fsrs_review(fsrs_card, rating, now)
    mastery.stability_days = updated_card.stability
    mastery.last_practiced_at = now
    mastery.next_review_at = updated_card.due  # Now properly set via FSRS scheduling

    # Bidirectional FIRe: propagate credit (correct) or doubt (incorrect) to prerequisites
    await _fire_propagate(db, user_id, node.id, course_id, correct)

    # LOOM consolidation: check if prerequisite groups are fully mastered
    await _consolidate_mastered_concepts(db, user_id, course_id, node.id)

    # Sync concept mastery → LearningProgress so forgetting_risk signals stay current
    await _sync_to_learning_progress(db, user_id, course_id, mastery)

    await db.flush()
    return mastery


# ── Bidirectional FIRe: Fractional Implicit Repetitions (GKT + FIRe) ──

async def _fire_propagate(
    db: AsyncSession,
    user_id: uuid.UUID,
    practiced_node_id: uuid.UUID,
    course_id: uuid.UUID,
    correct: bool,
    max_depth: int = 3,
) -> None:
    """Bidirectional FIRe: propagate credit or doubt to prerequisite concepts.

    Based on:
    - FIRe (2024): correct → boost prerequisite mastery (fractional implicit repetition)
    - GKT (Graph-based Knowledge Tracing): incorrect → reduce prerequisite mastery
      (if student fails concept A, prerequisites B, C may not be as solid as assumed)

    Propagation decays with depth: factor = 1/(depth+1)
    """
    # Get prerequisite edges from practiced node
    edges_result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_id == practiced_node_id,
            KnowledgeEdge.relation_type == "prerequisite",
        )
    )
    prereq_edges = edges_result.scalars().all()
    if not prereq_edges:
        return

    visited: set[uuid.UUID] = {practiced_node_id}
    queue: deque[tuple[uuid.UUID, int]] = deque((e.target_id, 1) for e in prereq_edges)

    while queue:
        prereq_id, depth = queue.popleft()
        if prereq_id in visited or depth > max_depth:
            continue
        visited.add(prereq_id)

        fraction = 1.0 / (depth + 1)

        mastery_result = await db.execute(
            select(ConceptMastery).where(
                ConceptMastery.user_id == user_id,
                ConceptMastery.knowledge_node_id == prereq_id,
            )
        )
        prereq_mastery = mastery_result.scalar_one_or_none()
        if prereq_mastery:
            if correct:
                # Positive FIRe: boost prerequisite mastery
                boost = fraction * FIRE_BOOST_PER_DEPTH
                prereq_mastery.mastery_score = min(1.0, prereq_mastery.mastery_score + boost)
            else:
                # GKT doubt propagation: reduce prerequisite mastery
                doubt = fraction * FIRE_DOUBT_PER_DEPTH
                prereq_mastery.mastery_score = max(0.0, prereq_mastery.mastery_score - doubt)

        # Continue walking up the prerequisite chain
        deeper_edges = await db.execute(
            select(KnowledgeEdge).where(
                KnowledgeEdge.source_id == prereq_id,
                KnowledgeEdge.relation_type == "prerequisite",
            )
        )
        for edge in deeper_edges.scalars().all():
            if edge.target_id not in visited:
                queue.append((edge.target_id, depth + 1))


# ── LOOM Concept Consolidation ──

async def _consolidate_mastered_concepts(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    updated_node_id: uuid.UUID,
) -> None:
    """Consolidate mastered prerequisite groups (LOOM paper, arXiv 2511.21037).

    When ALL prerequisites of a concept reach mastery > threshold:
    1. Boost the parent concept's mastery (foundation is solid)
    2. Extend stability of mastered prerequisites (reduce review frequency)
    """
    # Find concepts where this node is a prerequisite (i.e., parent concepts)
    parent_edges = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.target_id == updated_node_id,
            KnowledgeEdge.relation_type == "prerequisite",
        )
    )
    parent_ids = [e.source_id for e in parent_edges.scalars().all()]

    for parent_id in parent_ids:
        # Get all prerequisites of this parent
        prereq_edges = await db.execute(
            select(KnowledgeEdge).where(
                KnowledgeEdge.source_id == parent_id,
                KnowledgeEdge.relation_type == "prerequisite",
            )
        )
        prereq_ids = [e.target_id for e in prereq_edges.scalars().all()]
        if not prereq_ids:
            continue

        # Check if ALL prereqs are mastered
        masteries = await db.execute(
            select(ConceptMastery).where(
                ConceptMastery.user_id == user_id,
                ConceptMastery.knowledge_node_id.in_(prereq_ids),
            )
        )
        mastery_list = masteries.scalars().all()

        if len(mastery_list) < len(prereq_ids):
            continue  # Some prereqs not yet practiced

        all_mastered = all(m.mastery_score >= CONSOLIDATION_THRESHOLD for m in mastery_list)
        if not all_mastered:
            continue

        # All prereqs mastered! → Consolidate
        # 1. Boost parent mastery
        parent_mastery_result = await db.execute(
            select(ConceptMastery).where(
                ConceptMastery.user_id == user_id,
                ConceptMastery.knowledge_node_id == parent_id,
            )
        )
        pm = parent_mastery_result.scalar_one_or_none()
        if pm:
            pm.mastery_score = min(1.0, pm.mastery_score + CONSOLIDATION_PARENT_BOOST)
            logger.info(
                "Consolidated: parent concept %s boosted to %.3f (all prereqs mastered)",
                parent_id, pm.mastery_score,
            )

        # 2. Extend stability of mastered prereqs (space out reviews)
        for m in mastery_list:
            if m.stability_days and m.stability_days > 0:
                m.stability_days *= CONSOLIDATION_STABILITY_MULTIPLIER


# ── Mastery Sync: ConceptMastery → LearningProgress ──

async def _sync_to_learning_progress(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    concept_mastery: ConceptMastery,
) -> None:
    """Sync concept mastery changes to LearningProgress.

    This ensures that forgetting_risk signals (which read LearningProgress)
    reflect LOOM concept-level mastery updates from quiz and flashcard reviews.
    """
    try:
        from models.progress import LearningProgress

        result = await db.execute(
            select(LearningProgress).where(
                LearningProgress.user_id == user_id,
                LearningProgress.course_id == course_id,
            )
        )
        progress = result.scalar_one_or_none()
        if not progress:
            return

        # Sync FSRS scheduling data from concept mastery.
        # Use min strategy for next_review_at (earliest review wins) and
        # weighted blend for stability to avoid last-writer-wins overwrites.
        if concept_mastery.stability_days and concept_mastery.stability_days > 0:
            current_stability = progress.fsrs_stability or concept_mastery.stability_days
            progress.fsrs_stability = current_stability * 0.85 + concept_mastery.stability_days * 0.15
        if concept_mastery.next_review_at:
            if not progress.next_review_at or concept_mastery.next_review_at < progress.next_review_at:
                progress.next_review_at = concept_mastery.next_review_at
        # Blend mastery scores: nudge LearningProgress toward concept mastery
        if concept_mastery.mastery_score is not None:
            current = progress.mastery_score or 0.0
            # Small nudge (±0.05) to avoid overriding flashcard-specific mastery
            delta = (concept_mastery.mastery_score - current) * 0.15
            progress.mastery_score = max(0.0, min(1.0, current + delta))
    except (SQLAlchemyError, OSError) as e:
        logger.warning("ConceptMastery → LearningProgress sync failed: %s", e)
