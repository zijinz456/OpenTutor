"""LECTOR — LLM-Enhanced Concept-aware Tutoring and Optimized Review.

Based on: "LECTOR: A Semantic Spaced Repetition Framework" (arxiv:2508.03275)

Extends FSRS scheduling with semantic awareness from the LOOM knowledge graph:
1. Concept clustering: reviews related concepts together (not isolated cards)
2. Prerequisite priority: if a prerequisite concept is weak, review it first
3. Confusion-aware: concepts often confused together are reviewed in contrast
4. Decay propagation: when one concept decays, related concepts get a review boost

Usage:
    from services.lector import get_smart_review_session

    session = await get_smart_review_session(db, user_id, course_id, max_items=10)
    # Returns ordered list of concepts + practice items to review
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.knowledge_graph import KnowledgeNode, KnowledgeEdge, ConceptMastery
from services.spaced_repetition.fsrs import _retrievability as fsrs_retrievability

logger = logging.getLogger(__name__)


@dataclass
class ReviewItem:
    """A single item in a LECTOR review session."""
    concept_name: str
    concept_id: str
    mastery: float
    priority: float  # Higher = more urgent
    reason: str  # Why this is being reviewed
    related_concepts: list[str]  # Reviewed together for semantic reinforcement
    review_type: str = "standard"  # "standard" | "contrast" | "prerequisite_first"
    stability_days: float = 0.0
    retrievability: float = 1.0
    last_practiced_at: str | None = None
    content_node_id: str | None = None


async def get_smart_review_session(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    max_items: int = 10,
) -> list[ReviewItem]:
    """Generate a semantically-aware review session using LECTOR principles.

    Algorithm:
    1. Get all concepts with mastery data
    2. Score each concept by urgency (mastery decay + prerequisite risk)
    3. Cluster related concepts for co-review
    4. Return prioritized, clustered review list
    """
    # Get all concepts for this course
    result = await db.execute(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    )
    nodes = result.scalars().all()
    if not nodes:
        return []

    node_map = {n.id: n for n in nodes}
    node_ids = list(node_map.keys())

    # Get user mastery
    result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id.in_(node_ids),
        )
    )
    mastery_map = {m.knowledge_node_id: m for m in result.scalars().all()}

    # Get edges (prerequisites and related)
    result = await db.execute(
        select(KnowledgeEdge).where(
            KnowledgeEdge.source_id.in_(node_ids),
        )
    )
    edges = result.scalars().all()

    # Build adjacency maps
    prereqs_of: dict[uuid.UUID, list[uuid.UUID]] = {}  # concept → its prerequisites
    related_to: dict[uuid.UUID, list[uuid.UUID]] = {}
    confused_with: dict[uuid.UUID, list[uuid.UUID]] = {}

    for edge in edges:
        if edge.relation_type == "prerequisite":
            prereqs_of.setdefault(edge.source_id, []).append(edge.target_id)
        elif edge.relation_type == "related":
            related_to.setdefault(edge.source_id, []).append(edge.target_id)
        elif edge.relation_type == "confused_with":
            confused_with.setdefault(edge.source_id, []).append(edge.target_id)

    # Score each concept
    now = datetime.now(timezone.utc)
    scored_items: list[ReviewItem] = []

    for node in nodes:
        mastery = mastery_map.get(node.id)
        mastery_score = mastery.mastery_score if mastery else 0.0
        practice_count = mastery.practice_count if mastery else 0

        # ── Priority scoring (higher = more urgent) ──
        priority = 0.0
        reason_parts = []

        # Factor 1: Low mastery
        if mastery_score < settings.lector_mastery_threshold:
            priority += (settings.lector_mastery_threshold - mastery_score) * settings.lector_factor_low_mastery
            if mastery_score < 0.3:
                reason_parts.append("low mastery")

        # Factor 2: Never practiced
        if practice_count == 0:
            priority += settings.lector_factor_never_practiced
            reason_parts.append("not yet practiced")

        # Factor 3: Time decay — stability check
        if mastery and mastery.last_practiced_at:
            days_since = (now - mastery.last_practiced_at).total_seconds() / 86400
            stability = mastery.stability_days or 1.0
            if days_since > stability:
                decay = min((days_since - stability) / stability, 1.0)
                priority += decay * settings.lector_factor_time_decay
                reason_parts.append("memory decaying")

        # Factor 4: Prerequisite at risk (LECTOR key insight)
        # If this concept's prerequisites are weak, boost this concept's priority
        for prereq_id in prereqs_of.get(node.id, []):
            prereq_mastery = mastery_map.get(prereq_id)
            if prereq_mastery and prereq_mastery.mastery_score < settings.lector_prerequisite_threshold:
                priority += settings.lector_factor_prerequisite
                prereq_node = node_map.get(prereq_id)
                if prereq_node:
                    reason_parts.append(f"prerequisite '{prereq_node.name}' is weak")
                break  # Only count once

        # Factor 5: Confusion pair boost
        # If concepts are often confused, review them together
        for confused_id in confused_with.get(node.id, []):
            confused_mastery = mastery_map.get(confused_id)
            if confused_mastery and confused_mastery.mastery_score < settings.lector_confusion_threshold:
                priority += settings.lector_factor_confusion
                break

        # Factor 7: Proactive interference (LECTOR semantic interference matrix)
        # Boost priority for concepts with high-weight confused_with edges,
        # regardless of whether the confused concept has low mastery.
        # This catches potential confusion BEFORE the student makes a mistake.
        max_interference = 0.0
        for confused_id in confused_with.get(node.id, []):
            for edge in edges:
                if (edge.source_id == node.id and edge.target_id == confused_id
                        and edge.relation_type == "confused_with"
                        and edge.weight > max_interference):
                    max_interference = edge.weight
        if max_interference > 0.6:
            interference_boost = max_interference * settings.lector_factor_interference
            priority += interference_boost
            reason_parts.append("high semantic interference")

        # Factor 6: FSRS due card boost
        # If this concept has low stability or is overdue per FSRS schedule, boost priority
        if mastery and mastery.next_review_at:
            review_at = mastery.next_review_at
            if review_at.tzinfo is None:
                review_at = review_at.replace(tzinfo=timezone.utc)
            if review_at <= now:
                # Overdue — compute retrievability using FSRS-5/6 formula
                days_since = (now - mastery.last_practiced_at).total_seconds() / 86400 if mastery.last_practiced_at else 0
                stability = mastery.stability_days or 1.0
                retrievability = fsrs_retrievability(days_since, stability)
                fsrs_boost = (1.0 - retrievability) * settings.lector_factor_time_decay
                priority += fsrs_boost
                if fsrs_boost > 0.1:
                    reason_parts.append("FSRS overdue")

        if priority < 0.1:
            continue  # Skip well-mastered concepts

        # Build related concept list for co-review
        related_names = []
        for rel_id in related_to.get(node.id, [])[:3]:
            rel_node = node_map.get(rel_id)
            if rel_node:
                related_names.append(rel_node.name)

        reason = ", ".join(reason_parts) if reason_parts else "scheduled review"

        # Determine review type based on graph structure
        review_type = "standard"
        # Check for confusion pairs with low-mastery confused concepts
        confused_ids = confused_with.get(node.id, [])
        if confused_ids:
            for cid in confused_ids:
                cm = mastery_map.get(cid)
                if cm and cm.mastery_score < settings.lector_confusion_threshold:
                    review_type = "contrast"
                    break
        # Prerequisite-first overrides contrast when prerequisites are weak
        for prereq_id in prereqs_of.get(node.id, []):
            prereq_m = mastery_map.get(prereq_id)
            if prereq_m and prereq_m.mastery_score < settings.lector_prerequisite_threshold:
                review_type = "prerequisite_first"
                break

        # Compute retrievability for the response using FSRS-5/6
        item_stability = mastery.stability_days if mastery and mastery.stability_days else 0.0
        item_retrievability = 1.0
        if mastery and mastery.last_practiced_at and item_stability > 0:
            days_elapsed = (now - mastery.last_practiced_at).total_seconds() / 86400
            item_retrievability = fsrs_retrievability(days_elapsed, item_stability)

        scored_items.append(ReviewItem(
            concept_name=node.name,
            concept_id=str(node.id),
            mastery=mastery_score,
            priority=round(priority, 3),
            reason=reason,
            related_concepts=related_names,
            review_type=review_type,
            stability_days=round(item_stability, 2),
            retrievability=round(item_retrievability, 3),
            last_practiced_at=mastery.last_practiced_at.isoformat() if mastery and mastery.last_practiced_at else None,
            content_node_id=str(node.content_node_id) if getattr(node, "content_node_id", None) else None,
        ))

    # Sort by priority (highest first) and take top N
    scored_items.sort(key=lambda x: x.priority, reverse=True)
    return scored_items[:max_items]


async def get_review_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> dict:
    """Get a summary of what needs review, for the Heartbeat system.

    Returns:
        {
            "needs_review": bool,
            "urgent_count": int,
            "concepts_at_risk": ["Chain Rule", ...],
            "recommendation": str,
        }
    """
    items = await get_smart_review_session(db, user_id, course_id, max_items=20)

    urgent = [i for i in items if i.priority > 0.5]
    at_risk = [i.concept_name for i in urgent[:5]]

    if not items:
        return {
            "needs_review": False,
            "urgent_count": 0,
            "concepts_at_risk": [],
            "recommendation": "All caught up! No review needed.",
        }

    if len(urgent) >= 3:
        rec = f"You have {len(urgent)} concepts at risk. A quick review session would help reinforce: {', '.join(at_risk[:3])}."
    elif len(items) >= 1:
        rec = f"Consider reviewing: {items[0].concept_name} ({items[0].reason})."
    else:
        rec = "No urgent review needed."

    return {
        "needs_review": len(items) > 0,
        "urgent_count": len(urgent),
        "concepts_at_risk": at_risk,
        "recommendation": rec,
    }


async def record_review_outcome(
    db: AsyncSession,
    user_id: uuid.UUID,
    concept_id: uuid.UUID,
    recalled_correctly: bool,
) -> None:
    """Record whether a concept was recalled correctly after being reviewed.

    Delegates to FSRS review_card() for consistent scheduling with the
    rest of the system (quiz submissions, flashcard reviews).
    """
    from services.spaced_repetition.fsrs import FSRSCard, review_card as fsrs_review

    result = await db.execute(
        select(ConceptMastery).where(
            ConceptMastery.user_id == user_id,
            ConceptMastery.knowledge_node_id == concept_id,
        )
    )
    mastery = result.scalar_one_or_none()
    if mastery is None:
        logger.warning(
            "record_review_outcome: no ConceptMastery for user=%s concept=%s",
            user_id, concept_id,
        )
        return

    now = datetime.now(timezone.utc)
    fsrs_rating = 3 if recalled_correctly else 1  # Good vs Again

    fsrs_card = FSRSCard(
        difficulty=5.0,
        stability=mastery.stability_days if mastery.stability_days > 0 else 1.0,
        reps=mastery.practice_count,
        lapses=mastery.wrong_count,
        last_review=mastery.last_practiced_at,
        state="review" if mastery.practice_count > 0 else "new",
    )
    updated_card, _log = fsrs_review(fsrs_card, fsrs_rating, now)

    mastery.stability_days = updated_card.stability
    mastery.next_review_at = updated_card.due
    mastery.last_practiced_at = now
    mastery.practice_count += 1

    if recalled_correctly:
        mastery.correct_count += 1
        gain = 0.1 * (1.0 - mastery.mastery_score)
        mastery.mastery_score = min(1.0, mastery.mastery_score + gain)
    else:
        mastery.wrong_count += 1
        mastery.mastery_score = max(0.0, mastery.mastery_score - 0.1)

    await db.flush()
    logger.info(
        "Recorded review outcome: user=%s concept=%s recalled=%s mastery=%.3f stability=%.2f",
        user_id, concept_id, recalled_correctly,
        mastery.mastery_score, mastery.stability_days,
    )
