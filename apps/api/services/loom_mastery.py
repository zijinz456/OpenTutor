"""LOOM mastery — concept mastery tracking and FIRe propagation.

Handles updating mastery scores after practice/quiz attempts and
propagating fractional implicit repetition credit to prerequisites.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery

logger = logging.getLogger(__name__)


# ── Mastery Tracking ──

async def update_concept_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    concept_name: str,
    course_id: uuid.UUID,
    correct: bool,
) -> ConceptMastery | None:
    """Update mastery score for a concept after practice/quiz.

    Uses exponential moving average: new_score = alpha * result + (1 - alpha) * old_score
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
            stability_days=0.0,
        )
        db.add(mastery)

    # Update counters
    mastery.practice_count += 1
    if correct:
        mastery.correct_count += 1
    else:
        mastery.wrong_count += 1

    # Exponential moving average (alpha = 0.3 for responsiveness)
    alpha = 0.3
    result_score = 1.0 if correct else 0.0
    mastery.mastery_score = alpha * result_score + (1 - alpha) * mastery.mastery_score

    # FSRS-based stability and scheduling
    from services.spaced_repetition.fsrs import FSRSCard, review_card as fsrs_review

    fsrs_card = FSRSCard(
        difficulty=5.0,
        stability=mastery.stability_days if mastery.stability_days > 0 else 0.0,
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

    # FIRe: Fractional Implicit Repetitions — propagate partial credit to prerequisites
    await _fire_propagate(db, user_id, node.id, course_id, correct)

    await db.flush()
    return mastery


# ── FIRe: Fractional Implicit Repetitions ──

async def _fire_propagate(
    db: AsyncSession,
    user_id: uuid.UUID,
    practiced_node_id: uuid.UUID,
    course_id: uuid.UUID,
    correct: bool,
    max_depth: int = 3,
) -> None:
    """Propagate fractional review credit to prerequisite concepts.

    When a student practices concept A, prerequisite concepts B, C, ...
    receive implicit review credit proportional to 1/(depth+1).
    Reference: "Fractional Implicit Repetitions in Knowledge Graphs" (2024)
    """
    if not correct:
        return  # Only propagate on successful recall

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
    queue: list[tuple[uuid.UUID, int]] = [(e.target_id, 1) for e in prereq_edges]

    while queue:
        prereq_id, depth = queue.pop(0)
        if prereq_id in visited or depth > max_depth:
            continue
        visited.add(prereq_id)

        # Apply fractional credit
        fraction = 1.0 / (depth + 1)

        mastery_result = await db.execute(
            select(ConceptMastery).where(
                ConceptMastery.user_id == user_id,
                ConceptMastery.knowledge_node_id == prereq_id,
            )
        )
        prereq_mastery = mastery_result.scalar_one_or_none()
        if prereq_mastery:
            # Fractional boost: small mastery increase without full practice credit
            boost = fraction * 0.05  # 5% * fraction
            prereq_mastery.mastery_score = min(1.0, prereq_mastery.mastery_score + boost)

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
