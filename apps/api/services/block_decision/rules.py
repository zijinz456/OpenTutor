"""Block decision rules — deterministic signal-to-operation mappings.

Each rule function takes signal data and current block state,
returns a BlockOperation or None if the rule doesn't fire.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)

# Blocks that should never be hidden by the engine
PROTECTED_BLOCKS = frozenset({"notes", "quiz", "chapter_list"})

# Priority order for hiding blocks under cognitive overload
HIDE_PRIORITY = [
    "agent_insight", "forecast", "knowledge_graph",
    "progress", "plan", "wrong_answers", "flashcards", "review",
]


@dataclass
class BlockOperation:
    action: Literal["add", "remove", "resize", "reorder", "update_config"]
    block_type: str
    reason: str
    signal_source: str
    urgency: float  # 0-100
    config: dict = field(default_factory=dict)
    size: str | None = None


def rule_cognitive_overload(
    cognitive_load: dict | None,
    current_blocks: list[str],
) -> list[BlockOperation]:
    """High cognitive load → remove non-essential blocks."""
    if not cognitive_load:
        return []
    score = cognitive_load.get("score", 0)
    consecutive = cognitive_load.get("consecutive_high", 0)
    if score < 0.7 or consecutive < 2:
        return []

    ops = []
    removable = [bt for bt in HIDE_PRIORITY if bt in current_blocks and bt not in PROTECTED_BLOCKS]
    for bt in removable[:3]:  # Max 3 removals
        ops.append(BlockOperation(
            action="remove", block_type=bt,
            reason=f"Cognitive load is high ({score:.0%}). Simplifying your workspace.",
            signal_source="cognitive_load", urgency=90,
        ))
    return ops


def rule_cognitive_recovery(
    cognitive_load: dict | None,
    current_blocks: list[str],
    removed_for_load: list[str] | None = None,
) -> list[BlockOperation]:
    """Cognitive load dropped → restore blocks that were removed during overload."""
    if not cognitive_load or not removed_for_load:
        return []
    score = cognitive_load.get("score", 0)
    consecutive = cognitive_load.get("consecutive_high", 0)
    # Only recover when load is clearly low and sustained
    if score >= 0.4 or consecutive > 2:
        return []

    ops = []
    for bt in removed_for_load:
        if bt not in current_blocks and bt not in PROTECTED_BLOCKS:
            ops.append(BlockOperation(
                action="add", block_type=bt,
                reason="Cognitive load has eased. Restoring workspace.",
                signal_source="cognitive_recovery", urgency=30, size="medium",
            ))
    return ops


def rule_cognitive_adapt(
    cognitive_load: dict | None,
    current_blocks: list[str],
    current_mode: str | None = None,
) -> list[BlockOperation]:
    """Medium-high cognitive load → adapt quiz difficulty and suggest mode change.

    Fires at a lower threshold than rule_cognitive_overload (score >= 0.5)
    to provide early intervention before full overload.
    """
    if not cognitive_load:
        return []
    score = cognitive_load.get("score", 0)
    consecutive = cognitive_load.get("consecutive_high", 0)
    signals = cognitive_load.get("signals", {})
    ops = []

    # Moderate load: lower quiz difficulty to reduce pressure
    if score >= 0.5 and "quiz" in current_blocks:
        nlp_affect = signals.get("nlp_affect", 0)
        if nlp_affect >= 0.4 or (score >= 0.6 and consecutive >= 1):
            ops.append(BlockOperation(
                action="update_config", block_type="quiz",
                reason="Adjusting quiz difficulty to match your current pace.",
                signal_source="cognitive_load", urgency=70,
                config={"difficulty": "easy", "adaptive_reason": "cognitive_load"},
            ))

    # High load in exam_prep mode: suggest switching to self_paced
    # Only fire at very high thresholds to avoid over-notification
    if score >= 0.8 and consecutive >= 4 and current_mode == "exam_prep":
        if "agent_insight" not in current_blocks:
            ops.append(BlockOperation(
                action="add", block_type="agent_insight",
                reason="You've been studying intensively. Consider taking a lighter approach for a bit.",
                signal_source="cognitive_load", urgency=65, size="full",
                config={"insightType": "mode_suggestion", "suggestedMode": "self_paced"},
            ))

    return ops


def rule_forgetting_risk(
    signals: list[dict],
    current_blocks: list[str],
) -> BlockOperation | None:
    """Urgent forgetting risk → add review block."""
    forgetting = [s for s in signals if s.get("signal_type") == "forgetting_risk"]
    urgent_count = sum(1 for s in forgetting if s.get("urgency", 0) >= 70)
    if urgent_count >= 3 and "review" not in current_blocks:
        return BlockOperation(
            action="add", block_type="review",
            reason=f"{urgent_count} concepts at risk of being forgotten. Adding review.",
            signal_source="forgetting_risk", urgency=85, size="medium",
        )
    return None


def rule_frustration(
    cognitive_load: dict | None,
    current_blocks: list[str],
) -> list[BlockOperation]:
    """High frustration → remove quiz, add encouragement insight."""
    if not cognitive_load:
        return []
    signals = cognitive_load.get("signals", {})
    nlp_affect = signals.get("nlp_affect", 0)
    fatigue = signals.get("fatigue", 0)
    if nlp_affect < 0.6 and fatigue < 0.7:
        return []

    ops = []
    if "quiz" in current_blocks and nlp_affect >= 0.6:
        ops.append(BlockOperation(
            action="remove", block_type="quiz",
            reason="You seem frustrated. Removing quiz pressure for now.",
            signal_source="nlp_affect", urgency=85,
        ))
    return ops


def rule_deadline_approaching(
    signals: list[dict],
    current_blocks: list[str],
) -> BlockOperation | None:
    """Deadline within 3 days → add plan block."""
    deadlines = [s for s in signals if s.get("signal_type") == "deadline"]
    urgent_deadlines = [d for d in deadlines if d.get("urgency", 0) >= 80]
    if urgent_deadlines and "plan" not in current_blocks:
        detail = urgent_deadlines[0].get("detail", {})
        title = detail.get("title", "an assignment")
        return BlockOperation(
            action="add", block_type="plan",
            reason=f"Deadline approaching for {title}. Adding study plan.",
            signal_source="deadline", urgency=80, size="medium",
        )
    return None


def rule_prerequisite_gap(
    signals: list[dict],
    current_blocks: list[str],
) -> BlockOperation | None:
    """Prerequisite gaps detected → add knowledge graph."""
    gaps = [s for s in signals if s.get("signal_type") == "prerequisite_gap"]
    if len(gaps) >= 1 and "knowledge_graph" not in current_blocks:
        return BlockOperation(
            action="add", block_type="knowledge_graph",
            reason="Found prerequisite gaps. Adding knowledge graph to visualize dependencies.",
            signal_source="prerequisite_gap", urgency=75, size="medium",
        )
    return None


def rule_mastery_gate(
    signals: list[dict],
    current_blocks: list[str],
) -> BlockOperation | None:
    """Multiple prerequisite gaps → show insight suggesting prerequisite review."""
    gaps = [s for s in signals if s.get("signal_type") == "prerequisite_gap"]
    if len(gaps) >= 2 and "agent_insight" not in current_blocks:
        gap_concepts = [s.get("concept", "unknown") for s in gaps[:3]]
        return BlockOperation(
            action="add", block_type="agent_insight",
            reason=(
                f"Prerequisites not yet mastered: {', '.join(gap_concepts)}. "
                "Recommend reviewing these before advancing."
            ),
            signal_source="prerequisite_gap", urgency=80, size="small",
            config={"insightType": "mastery_gate", "concepts": gap_concepts},
        )
    return None


def rule_weak_areas(
    signals: list[dict],
    current_blocks: list[str],
) -> BlockOperation | None:
    """Many weak areas → add wrong_answers block."""
    weak = [s for s in signals if s.get("signal_type") == "weak_area"]
    if len(weak) >= 3 and "wrong_answers" not in current_blocks:
        return BlockOperation(
            action="add", block_type="wrong_answers",
            reason=f"{len(weak)} weak areas detected. Adding error analysis.",
            signal_source="weak_area", urgency=70, size="medium",
        )
    return None


def rule_confusion_pairs(
    signals: list[dict],
    current_blocks: list[str],
) -> BlockOperation | None:
    """Confusion pairs detected → update quiz config for targeted questions."""
    layout_signals = [s for s in signals if s.get("signal_type") == "layout_adaptation"]
    for sig in layout_signals:
        detail = sig.get("detail", {})
        confused = detail.get("confused_pairs", [])
        if len(confused) >= 2 and "quiz" in current_blocks:
            concepts = [p[0] for p in confused[:3]] if confused else []
            return BlockOperation(
                action="update_config", block_type="quiz",
                reason=f"Confusion detected between concepts. Targeting quiz questions.",
                signal_source="confusion_pairs", urgency=65,
                config={"target_concepts": concepts, "difficulty": "adaptive"},
            )
    return None


def rule_inactivity(
    signals: list[dict],
    current_blocks: list[str],
) -> BlockOperation | None:
    """Inactive for 3+ days → add welcome-back insight."""
    inactive = [s for s in signals if s.get("signal_type") == "inactivity"]
    if inactive and "agent_insight" not in current_blocks:
        return BlockOperation(
            action="add", block_type="agent_insight",
            reason="Welcome back! You have concepts to review.",
            signal_source="inactivity", urgency=60, size="full",
            config={"insightType": "welcome_back"},
        )
    return None


def rule_lector_review(
    signals: list[dict],
    current_blocks: list[str],
) -> list[BlockOperation]:
    """LECTOR semantic review signals → targeted block operations.

    When LECTOR detects concepts needing review based on knowledge graph
    relationships (prerequisite weakness, confusion pairs, decay), surface
    the appropriate blocks.
    """
    lector = [s for s in signals if s.get("signal_type") == "lector_review"]
    if not lector:
        return []

    ops = []
    detail = lector[0].get("detail", {})
    urgent_count = detail.get("urgent_count", 0)
    prereq_count = detail.get("prereq_first_count", 0)
    contrast_count = detail.get("contrast_count", 0)
    confused = detail.get("confused_concepts", [])
    weak_prereqs = detail.get("weak_prerequisites", [])

    # If prerequisites are weak, surface knowledge graph for visualization
    if prereq_count >= 1 and "knowledge_graph" not in current_blocks:
        ops.append(BlockOperation(
            action="add", block_type="knowledge_graph",
            reason=f"Prerequisite concepts need attention: {', '.join(weak_prereqs[:2])}. "
                   "Showing knowledge graph to visualize dependencies.",
            signal_source="lector_review", urgency=80, size="medium",
        ))

    # If confusion pairs detected, update quiz to target confused concepts
    if contrast_count >= 1 and "quiz" in current_blocks and confused:
        ops.append(BlockOperation(
            action="update_config", block_type="quiz",
            reason=f"Concepts often confused: {', '.join(confused[:2])}. Targeting quiz questions.",
            signal_source="lector_review", urgency=75,
            config={"target_concepts": confused[:3], "difficulty": "adaptive", "review_mode": "contrast"},
        ))

    # If many urgent items and no review block, add it
    if urgent_count >= 3 and "review" not in current_blocks:
        concepts = detail.get("concepts", [])
        ops.append(BlockOperation(
            action="add", block_type="review",
            reason=f"{urgent_count} concepts need semantic review: {', '.join(concepts[:3])}.",
            signal_source="lector_review", urgency=82, size="medium",
        ))

    # Proactive review session CTA when many concepts are at risk
    if urgent_count >= 3 and "agent_insight" not in current_blocks:
        concepts = detail.get("concepts", [])
        ops.append(BlockOperation(
            action="add", block_type="agent_insight",
            reason=f"{urgent_count} concepts at risk of being forgotten. Start a review session?",
            signal_source="lector_review_cta", urgency=85, size="small",
            config={
                "insightType": "review_session_cta",
                "urgent_count": urgent_count,
                "concepts": concepts[:5],
            },
        ))

    return ops


def rule_mastery_complete(
    signals: list[dict],
    current_blocks: list[str],
    current_mode: str | None,
) -> BlockOperation | None:
    """All concepts mastered → suggest maintenance mode."""
    # Only fire when we actually received signals (empty list = collection failed)
    if not signals:
        return None
    weak = [s for s in signals if s.get("signal_type") in ("weak_area", "forgetting_risk")]
    if not weak and current_mode != "maintenance" and current_blocks:
        return BlockOperation(
            action="add", block_type="agent_insight",
            reason="Great progress! All concepts look solid. Consider switching to maintenance mode.",
            signal_source="mastery_complete", urgency=50, size="full",
            config={"insightType": "mode_suggestion", "suggestedMode": "maintenance"},
        )
    return None
