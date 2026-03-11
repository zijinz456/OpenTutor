"""LECTOR Session Structure -- Interleaved review with warm-up and peak-end ordering.

Based on:
- Interleaving effect (Rohrer & Taylor, 2007)
- Peak-end rule (Kahneman et al., 1993)

Usage:
    from services.lector_session import build_structured_session

    structured = await build_structured_session(items, max_items=10)
"""

import logging
from services.lector import ReviewItem

logger = logging.getLogger(__name__)


async def build_structured_session(
    items: list[ReviewItem],
    max_items: int = 10,
) -> list[ReviewItem]:
    """Structure review items using learning science principles.

    1. Warm-up: Start with 1-2 high-mastery items (quick wins)
    2. Interleave: Alternate between different concept types/domains
    3. Peak-end: End with the most challenging item (peak-end rule)
    4. Contrast pairs: Place confused concepts adjacent for comparison
    """
    if not items:
        return []

    # Truncate to max_items first (items arrive pre-sorted by priority desc)
    pool = list(items[:max_items])

    # ── Phase 1: Extract warm-up candidates (high mastery, easy wins) ──
    warm_up: list[ReviewItem] = []
    rest: list[ReviewItem] = []
    for item in pool:
        if item.mastery > 0.5 and len(warm_up) < 2:
            warm_up.append(item)
        else:
            rest.append(item)

    # If we didn't find enough warm-up items, just use what we have
    if not warm_up and rest:
        # Pick the highest-mastery item as a single warm-up
        rest.sort(key=lambda x: x.mastery, reverse=True)
        warm_up.append(rest.pop(0))

    # ── Phase 2: Identify peak-end item (highest priority in rest) ──
    peak_end: ReviewItem | None = None
    if rest:
        rest.sort(key=lambda x: x.priority, reverse=True)
        peak_end = rest.pop(0)

    # ── Phase 2.5: Extract prerequisite_first items (must come early) ──
    prereq_items: list[ReviewItem] = []
    rest_after_prereq: list[ReviewItem] = []
    for item in rest:
        if item.review_type == "prerequisite_first":
            prereq_items.append(item)
        else:
            rest_after_prereq.append(item)
    rest = rest_after_prereq

    # ── Phase 3: Group contrast pairs together ──
    contrast_items: list[ReviewItem] = []
    non_contrast: list[ReviewItem] = []
    for item in rest:
        if item.review_type == "contrast":
            contrast_items.append(item)
        else:
            non_contrast.append(item)

    # ── Phase 4: Interleave non-contrast items by related_concepts groups ──
    interleaved = _interleave_by_group(non_contrast)

    # ── Phase 5: Insert contrast pairs adjacent to each other ──
    # Group contrast items by shared related_concepts for adjacency
    contrast_pairs = _build_contrast_pairs(contrast_items)

    # ── Phase 6: Assemble final session ──
    session: list[ReviewItem] = []
    session.extend(warm_up)
    session.extend(prereq_items)        # Prerequisites before dependent concepts
    session.extend(contrast_pairs)
    session.extend(interleaved)
    if peak_end is not None:
        session.append(peak_end)

    logger.info(
        "Built structured session: %d items (warm-up=%d, prereq=%d, contrast=%d, interleaved=%d, peak-end=%s)",
        len(session), len(warm_up), len(prereq_items), len(contrast_pairs),
        len(interleaved), peak_end is not None,
    )
    return session


def _interleave_by_group(items: list[ReviewItem]) -> list[ReviewItem]:
    """Interleave items so that consecutive items come from different concept groups.

    Groups items by their first related_concept (as a proxy for domain/topic),
    then round-robin picks from each group.
    """
    if len(items) <= 1:
        return items

    groups: dict[str, list[ReviewItem]] = {}
    for item in items:
        # Use first related concept as group key, or concept_name itself
        group_key = item.related_concepts[0] if item.related_concepts else item.concept_name
        groups.setdefault(group_key, []).append(item)

    # Round-robin across groups
    result: list[ReviewItem] = []
    group_lists = list(groups.values())
    max_len = max(len(g) for g in group_lists) if group_lists else 0
    for i in range(max_len):
        for group in group_lists:
            if i < len(group):
                result.append(group[i])
    return result


def _build_contrast_pairs(items: list[ReviewItem]) -> list[ReviewItem]:
    """Order contrast-type items so related concepts appear adjacent.

    Sorts by concept_name so that concepts sharing related_concepts
    end up near each other naturally.
    """
    if len(items) <= 1:
        return items

    # Sort by related_concepts (joined) so concepts with shared relations cluster
    items.sort(key=lambda x: ",".join(sorted(x.related_concepts)))
    return items
