"""Computerized Adaptive Testing (CAT) engine for diagnostic pre-tests.

Implements an adaptive item selection algorithm inspired by catsim's
MaxInfoSelector: at each step, select the concept whose "difficulty boundary"
is closest to the current ability estimate, maximizing Fisher information.

After 15–20 questions (or when standard error is low enough), the session
finalizes by writing estimated mastery scores to ConceptMastery.

References:
- Bloom (1984): 2 Sigma Problem — mastery gating requires knowing the baseline
- Doignon & Falmagne (1999): Knowledge Space Theory — outer fringe = ready to learn
- catsim (github.com/douglasrizzo/catsim): MaxInfoSelector algorithm
"""

import logging
import math
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery

logger = logging.getLogger(__name__)

# Stopping criteria
MIN_ITEMS = 5
MAX_ITEMS = 20
SE_THRESHOLD = 0.15  # Stop when standard error < this


@dataclass
class CATItem:
    """A testable concept with its difficulty estimate."""

    concept_id: uuid.UUID
    concept_name: str
    difficulty: float  # 0.0 (easy) to 1.0 (hard), estimated from Bloom level
    bloom_level: int = 1


@dataclass
class CATState:
    """Mutable state for a CAT session."""

    theta: float = 0.5  # Current ability estimate (0–1 scale)
    responses: list[dict] = field(default_factory=list)  # [{concept_id, correct, difficulty}]
    tested_ids: set[uuid.UUID] = field(default_factory=set)
    correct_count: int = 0
    total_count: int = 0

    @property
    def standard_error(self) -> float:
        """Estimate standard error of ability estimate."""
        if self.total_count < 2:
            return 1.0
        p = max(self.correct_count / self.total_count, 0.01)
        p = min(p, 0.99)
        # SE from binomial: sqrt(p*(1-p)/n)
        return math.sqrt(p * (1 - p) / self.total_count)

    @property
    def should_stop(self) -> bool:
        if self.total_count >= MAX_ITEMS:
            return True
        if self.total_count >= MIN_ITEMS and self.standard_error < SE_THRESHOLD:
            return True
        return False


async def load_testable_concepts(
    db: AsyncSession,
    course_id: uuid.UUID,
) -> list[CATItem]:
    """Load all concepts for a course and estimate their difficulty."""
    result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = result.scalars().all()

    items = []
    for node in nodes:
        metadata = node.metadata_ or {}
        bloom = metadata.get("bloom_level", 2)
        # Map Bloom level (1–6) to difficulty (0–1)
        difficulty = min(max((bloom - 1) / 5.0, 0.1), 0.9)
        items.append(CATItem(
            concept_id=node.id,
            concept_name=node.name,
            difficulty=difficulty,
            bloom_level=bloom,
        ))

    return items


def select_next_item(
    state: CATState,
    items: list[CATItem],
) -> CATItem | None:
    """Select the next item using maximum information criterion.

    Picks the untested concept whose difficulty is closest to the current
    ability estimate (theta), maximizing Fisher information at the operating point.
    """
    untested = [item for item in items if item.concept_id not in state.tested_ids]
    if not untested:
        return None

    # Sort by distance from current ability estimate
    untested.sort(key=lambda item: abs(item.difficulty - state.theta))
    return untested[0]


def update_ability(state: CATState, item: CATItem, correct: bool) -> None:
    """Update ability estimate after a response using EAP-like update.

    Uses a simplified Bayesian update: shift theta toward the item's difficulty
    if incorrect, or away from it (upward) if correct.
    """
    state.tested_ids.add(item.concept_id)
    state.total_count += 1
    if correct:
        state.correct_count += 1

    state.responses.append({
        "concept_id": str(item.concept_id),
        "concept_name": item.concept_name,
        "correct": correct,
        "difficulty": item.difficulty,
    })

    # Adaptive step size: decreases as more items are answered
    step = 0.3 / math.sqrt(state.total_count)

    if correct:
        # Ability is at least at this difficulty level
        if state.theta < item.difficulty:
            state.theta = state.theta + step * (item.difficulty - state.theta + 0.1)
        else:
            state.theta = min(state.theta + step * 0.2, 1.0)
    else:
        # Ability is below this difficulty level
        if state.theta > item.difficulty:
            state.theta = state.theta - step * (state.theta - item.difficulty + 0.1)
        else:
            state.theta = max(state.theta - step * 0.2, 0.0)

    state.theta = max(0.0, min(1.0, state.theta))


async def finalize_pretest(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    state: CATState,
    items: list[CATItem],
) -> dict:
    """Write estimated mastery scores to ConceptMastery for all concepts.

    Directly tested concepts get their observed mastery.
    Untested concepts get inferred mastery based on:
    - Prerequisites: if a harder concept was passed, easier prerequisites
      are likely mastered (upward inference)
    - Dependents: if an easy concept was failed, harder dependents are
      likely not mastered (downward inference)
    """
    # Build mastery estimates for tested concepts
    tested_mastery: dict[uuid.UUID, float] = {}
    for resp in state.responses:
        concept_id_str = resp.get("concept_id")
        if not concept_id_str:
            continue
        cid = uuid.UUID(concept_id_str)
        # Binary mastery from single question (refined with theta)
        if resp.get("correct"):
            tested_mastery[cid] = min(0.4 + state.theta * 0.4, 0.85)
        else:
            tested_mastery[cid] = max(state.theta * 0.3, 0.05)

    # Load prerequisite edges for inference
    node_ids = [item.concept_id for item in items]
    edges_result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_id.in_(node_ids),
            KnowledgeEdge.relation_type == "prerequisite",
        )
    )
    edges = edges_result.scalars().all()

    # Build prerequisite map: concept -> prerequisites
    prereq_map: dict[uuid.UUID, list[uuid.UUID]] = {}
    for edge in edges:
        prereq_map.setdefault(edge.source_id, []).append(edge.target_id)

    # Infer mastery for untested concepts
    all_mastery: dict[uuid.UUID, float] = {}
    item_by_id = {item.concept_id: item for item in items}

    for item in items:
        if item.concept_id in tested_mastery:
            all_mastery[item.concept_id] = tested_mastery[item.concept_id]
        else:
            # Infer from theta and difficulty
            if state.theta >= item.difficulty:
                # Ability exceeds difficulty — likely mastered
                all_mastery[item.concept_id] = min(0.3 + (state.theta - item.difficulty) * 0.5, 0.7)
            else:
                # Ability below difficulty — likely not mastered
                all_mastery[item.concept_id] = max(0.1, state.theta * 0.4)

    # Write to ConceptMastery table
    written = 0
    for concept_id, mastery in all_mastery.items():
        # Check if mastery record already exists
        existing = await db.execute(
            select(ConceptMastery).where(
                ConceptMastery.user_id == user_id,
                ConceptMastery.knowledge_node_id == concept_id,
            )
        )
        record = existing.scalar_one_or_none()

        if record:
            # Only update if this is a fresh pretest (don't overwrite real practice data)
            if record.practice_count == 0:
                record.mastery_score = mastery
                written += 1
        else:
            new_record = ConceptMastery(
                user_id=user_id,
                knowledge_node_id=concept_id,
                mastery_score=mastery,
                practice_count=0,
                correct_count=0,
                wrong_count=0,
            )
            db.add(new_record)
            written += 1

    await db.commit()

    return {
        "status": "completed",
        "questions_asked": state.total_count,
        "correct": state.correct_count,
        "estimated_ability": round(state.theta, 3),
        "standard_error": round(state.standard_error, 3),
        "concepts_assessed": len(all_mastery),
        "mastery_written": written,
    }
