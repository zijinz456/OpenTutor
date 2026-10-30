"""LOOM concept mastery — the derived, concept-level view of the mastery ledger.

Ledger principle
----------------
``learning_progress`` (per content node) is the source of truth the UI reads;
``concept_mastery`` (per LOOM knowledge node) is a *derived* view of the same
attempt facts.  Both are only ever updated from attempt events (a graded quiz
answer, a flashcard rating, a review rating) and both run the same Bayesian
Knowledge Tracing step from ``services.learning_science.knowledge_tracer``.
No LLM output ever writes a mastery number.

Every value in ``concept_mastery`` is recomputable by replaying the attempt
sequence through this module:

1. BKT step (shared tracer, guess rate chosen by question type)::

       P(L|correct)   = P(L)(1-s) / [P(L)(1-s) + (1-P(L)) g]
       P(L|incorrect) = P(L) s     / [P(L) s     + (1-P(L))(1-g)]
       P(L_next)      = P(L|obs) + (1 - P(L|obs)) * p_t

2. FSRS scheduling (shared ``services.spaced_repetition.fsrs.review_card``)
   with rating Good (3) for correct and Again (1) for incorrect; the card is
   rebuilt from the row's own counters, so ``stability_days`` and
   ``next_review_at`` are a pure function of the attempt history.

3. FIRe prerequisite propagation (deterministic, depth <= 3)::

       correct:   prereq.mastery += FIRE_BOOST_PER_DEPTH / (depth + 1)
       incorrect: prereq.mastery -= FIRE_DOUBT_PER_DEPTH / (depth + 1)

4. LOOM consolidation (correct attempts only): when every prerequisite of a
   parent concept is at or above ``CONSOLIDATION_THRESHOLD``, the parent gets
   ``+CONSOLIDATION_PARENT_BOOST`` and each prerequisite's stability is
   multiplied by ``CONSOLIDATION_STABILITY_MULTIPLIER``.

Academic foundations: BKT (Corbett & Anderson 1994; pyBKT guess/slip by
question type), GKT doubt propagation, FIRe (2024), LOOM (arXiv 2511.21037).
"""

import logging
import uuid
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery
from services.learning_science.knowledge_tracer import (
    BKTState,
    params_for_question_type,
    update_mastery as bkt_step,
)

logger = logging.getLogger(__name__)

# ── FIRe Parameters ──
FIRE_BOOST_PER_DEPTH = 0.05   # 5% mastery boost per FIRe propagation level (correct)
FIRE_DOUBT_PER_DEPTH = 0.03   # 3% mastery reduction per depth level (incorrect, GKT-inspired)

# ── Consolidation Parameters (LOOM paper) ──
CONSOLIDATION_THRESHOLD = 0.85          # All prereqs must exceed this mastery
CONSOLIDATION_PARENT_BOOST = 0.1        # Mastery boost for parent concept
CONSOLIDATION_STABILITY_MULTIPLIER = 1.5  # Extend review interval for mastered prereqs


def rating_is_correct(rating: int) -> bool:
    """Map an FSRS rating (1=Again, 2=Hard, 3=Good, 4=Easy) to a binary attempt fact."""
    return rating >= 3


async def _resolve_node(
    db: AsyncSession,
    course_id: uuid.UUID | None,
    concept_name: str | None,
    knowledge_node_id: uuid.UUID | None,
) -> KnowledgeNode | None:
    if knowledge_node_id is not None:
        result = await db.execute(select(KnowledgeNode).where(KnowledgeNode.id == knowledge_node_id))
        return result.scalar_one_or_none()
    if not concept_name or course_id is None:
        return None
    result = await db.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.course_id == course_id,
            func.lower(KnowledgeNode.name) == concept_name.lower(),
        )
    )
    return result.scalar_one_or_none()


async def update_concept_mastery(
    db: AsyncSession,
    user_id: uuid.UUID,
    concept_name: str | None,
    course_id: uuid.UUID | None,
    correct: bool,
    question_type: str | None = None,
    *,
    knowledge_node_id: uuid.UUID | None = None,
    rating: int | None = None,
) -> ConceptMastery | None:
    """Apply one attempt fact to a concept's derived mastery row.

    The concept is resolved by ``knowledge_node_id`` when given (the id stored
    on ``problem_metadata`` / card JSON at ingestion), otherwise by normalized
    name within ``course_id``.  ``rating`` (FSRS 1-4) is used for scheduling
    when supplied; otherwise correct→Good, incorrect→Again.
    """
    node = await _resolve_node(db, course_id, concept_name, knowledge_node_id)
    if not node:
        return None
    course_id = course_id or node.course_id

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

    mastery.practice_count += 1
    if correct:
        mastery.correct_count += 1
    else:
        mastery.wrong_count += 1

    # 1. Shared BKT step
    state = bkt_step(
        BKTState(p_mastery=mastery.mastery_score or 0.0, observations=mastery.practice_count - 1),
        correct,
        params_for_question_type(question_type),
    )
    mastery.mastery_score = state.p_mastery

    # 2. Shared FSRS scheduling
    from services.spaced_repetition.fsrs import FSRSCard, review_card as fsrs_review

    fsrs_card = FSRSCard(
        difficulty=5.0,
        stability=mastery.stability_days if mastery.stability_days > 0 else 1.0,
        reps=mastery.practice_count - 1,  # -1 because we already incremented
        lapses=mastery.wrong_count,
        last_review=mastery.last_practiced_at,
        state="review" if mastery.practice_count > 1 else "new",
    )
    fsrs_rating = rating if rating in (1, 2, 3, 4) else (3 if correct else 1)
    now = datetime.now(timezone.utc)
    updated_card, _ = fsrs_review(fsrs_card, fsrs_rating, now)
    mastery.stability_days = updated_card.stability
    mastery.last_practiced_at = now
    mastery.next_review_at = updated_card.due

    # 3. Bidirectional FIRe: propagate credit (correct) or doubt (incorrect) to prerequisites
    await _fire_propagate(db, user_id, node.id, course_id, correct)

    # 4. LOOM consolidation: only a correct attempt can complete a mastered group
    if correct:
        await _consolidate_mastered_concepts(db, user_id, course_id, node.id)

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
                boost = fraction * FIRE_BOOST_PER_DEPTH
                prereq_mastery.mastery_score = min(1.0, prereq_mastery.mastery_score + boost)
            else:
                doubt = fraction * FIRE_DOUBT_PER_DEPTH
                prereq_mastery.mastery_score = max(0.0, prereq_mastery.mastery_score - doubt)

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
    parent_edges = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.target_id == updated_node_id,
            KnowledgeEdge.relation_type == "prerequisite",
        )
    )
    parent_ids = [e.source_id for e in parent_edges.scalars().all()]

    for parent_id in parent_ids:
        prereq_edges = await db.execute(
            select(KnowledgeEdge).where(
                KnowledgeEdge.source_id == parent_id,
                KnowledgeEdge.relation_type == "prerequisite",
            )
        )
        prereq_ids = [e.target_id for e in prereq_edges.scalars().all()]
        if not prereq_ids:
            continue

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

        for m in mastery_list:
            if m.stability_days and m.stability_days > 0:
                m.stability_days *= CONSOLIDATION_STABILITY_MULTIPLIER
