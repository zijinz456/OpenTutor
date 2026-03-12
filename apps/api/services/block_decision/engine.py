"""Block Decision Engine — consumes all signals, outputs block operations.

Deterministic rule engine (no LLM calls). Each rule evaluates independently,
results are sorted by urgency, capped at MAX_OPS_PER_TURN, and filtered
against dismiss history.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .rules import (
    BlockOperation,
    rule_cognitive_adapt,
    rule_cognitive_overload,
    rule_cognitive_recovery,
    rule_confusion_pairs,
    rule_deadline_approaching,
    rule_forgetting_risk,
    rule_frustration,
    rule_inactivity,
    rule_lector_review,
    rule_mastery_complete,
    rule_mastery_gate,
    rule_prerequisite_gap,
    rule_weak_areas,
)

logger = logging.getLogger(__name__)

MAX_OPS_PER_TURN = 2


class BlockDecisionResult:
    """Container for block decision engine output."""

    __slots__ = ("operations", "cognitive_state", "explanation", "intervention_ids")

    def __init__(
        self,
        operations: list[BlockOperation],
        cognitive_state: dict,
        explanation: str,
        intervention_ids: dict[str, str] | None = None,
    ):
        self.operations = operations
        self.cognitive_state = cognitive_state
        self.explanation = explanation
        self.intervention_ids = intervention_ids or {}

    def to_dict(self) -> dict:
        result = {
            "operations": [asdict(op) for op in self.operations],
            "cognitive_state": self.cognitive_state,
            "explanation": self.explanation,
        }
        if self.intervention_ids:
            result["intervention_ids"] = self.intervention_ids
        return result


async def compute_block_decisions(
    db: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    current_blocks: list[str],
    current_mode: str | None,
    cognitive_load: dict | None,
    dismissed_types: list[str],
    signals: list[dict] | None = None,
    preferences: dict | None = None,
    removed_for_load: list[str] | None = None,
) -> BlockDecisionResult:
    """Evaluate all rules against current state and return block operations.

    Parameters
    ----------
    db : AsyncSession
    user_id, course_id : identifiers
    current_blocks : list of block type strings currently in workspace
    current_mode : learning mode (course_following, self_paced, etc.)
    cognitive_load : cognitive load analysis dict from compute_cognitive_load
    dismissed_types : block types the user recently dismissed
    signals : agenda signals (from collect_signals), as list of dicts
    preferences : block preference scores (from preference engine), optional
    """
    if signals is None:
        signals = []

    # Collect all candidate operations from rules
    candidates: list[BlockOperation] = []

    # Rule: cognitive overload
    overload_ops = rule_cognitive_overload(cognitive_load, current_blocks)
    candidates.extend(overload_ops)

    # Rule: cognitive recovery (restore blocks removed during overload)
    if not overload_ops:
        candidates.extend(rule_cognitive_recovery(
            cognitive_load, current_blocks, removed_for_load,
        ))

    # Rule: cognitive adaptation (quiz difficulty, mode suggestion)
    candidates.extend(rule_cognitive_adapt(cognitive_load, current_blocks, current_mode))

    # Rule: frustration
    candidates.extend(rule_frustration(cognitive_load, current_blocks))

    # Rule: forgetting risk
    op = rule_forgetting_risk(signals, current_blocks)
    if op:
        candidates.append(op)

    # Rule: deadline approaching
    op = rule_deadline_approaching(signals, current_blocks)
    if op:
        candidates.append(op)

    # Rule: prerequisite gaps
    op = rule_prerequisite_gap(signals, current_blocks)
    if op:
        candidates.append(op)

    # Rule: mastery gate (stronger prerequisite warning)
    op = rule_mastery_gate(signals, current_blocks)
    if op:
        candidates.append(op)

    # Rule: weak areas
    op = rule_weak_areas(signals, current_blocks)
    if op:
        candidates.append(op)

    # Rule: confusion pairs
    op = rule_confusion_pairs(signals, current_blocks)
    if op:
        candidates.append(op)

    # Rule: LECTOR semantic review
    candidates.extend(rule_lector_review(signals, current_blocks))

    # Rule: inactivity
    op = rule_inactivity(signals, current_blocks)
    if op:
        candidates.append(op)

    # Rule: mastery complete
    op = rule_mastery_complete(signals, current_blocks, current_mode)
    if op:
        candidates.append(op)

    # ── Filtering ──

    # 1. Don't re-add dismissed types (within dismiss window)
    candidates = [
        c for c in candidates
        if not (c.action == "add" and c.block_type in dismissed_types)
    ]

    # 2. Don't add blocks that already exist
    candidates = [
        c for c in candidates
        if not (c.action == "add" and c.block_type in current_blocks)
    ]

    # 3. Conflict resolution: remove supersedes update_config for same block
    # (e.g. rule_cognitive_overload removes quiz while rule_cognitive_adapt updates it)
    removed_types = {c.block_type for c in candidates if c.action == "remove"}
    candidates = [
        c for c in candidates
        if not (c.action == "update_config" and c.block_type in removed_types)
    ]

    # 4. Apply preference-based filtering
    if preferences:
        block_scores = preferences.get("block_scores", {})
        blocked_types = set(preferences.get("blocked", []))
        filtered = []
        for c in candidates:
            if c.block_type in blocked_types and c.action == "add":
                continue  # User explicitly blocked this type
            score_data = block_scores.get(c.block_type, {})
            dismiss_count = score_data.get("dismiss_count", 0)
            if dismiss_count >= 3 and c.action == "add":
                continue  # User consistently dismisses this type
            # Lower urgency for low-score blocks
            pref_score = score_data.get("score", 0)
            if pref_score < -0.3 and c.action == "add":
                c.urgency *= 0.5
            filtered.append(c)
        candidates = filtered

    # ── Sort by urgency and cap ──
    candidates.sort(key=lambda c: c.urgency, reverse=True)
    selected = candidates[:MAX_OPS_PER_TURN]

    # ── Record intervention outcomes for cognitive/affect-based ops ──
    _TRACKED_SOURCES = {"cognitive_load", "cognitive_recovery", "nlp_affect", "frustration"}
    cl_score_now = cognitive_load.get("score", 0) if cognitive_load else 0
    intervention_ids: dict[str, str] = {}  # block_type → intervention_id
    for op in selected:
        if op.signal_source in _TRACKED_SOURCES:
            try:
                import uuid as _uuid
                from models.intervention_outcome import InterventionOutcome
                outcome_id = _uuid.uuid4()
                db.add(InterventionOutcome(
                    id=outcome_id,
                    user_id=user_id,
                    course_id=course_id,
                    intervention_type=op.action,
                    block_type=op.block_type,
                    signal_source=op.signal_source,
                    reason=op.reason,
                    cognitive_load_before=cl_score_now,
                ))
                intervention_ids[op.block_type] = str(outcome_id)
            except (SQLAlchemyError, ValueError, TypeError, RuntimeError):
                logger.warning("Failed to record intervention outcome", exc_info=True)

    # ── Build cognitive state summary ──
    cl_score = cognitive_load.get("score", 0) if cognitive_load else 0
    cl_level = cognitive_load.get("level", "low") if cognitive_load else "low"
    top_signals = []
    if cognitive_load and cognitive_load.get("signals"):
        sorted_sigs = sorted(
            cognitive_load["signals"].items(),
            key=lambda x: x[1], reverse=True,
        )
        top_signals = [{"name": k, "value": round(v, 2)} for k, v in sorted_sigs[:3]]

    cognitive_state = {
        "score": round(cl_score, 2),
        "level": cl_level,
        "top_signals": top_signals,
    }

    # ── Build explanation ──
    if not selected:
        explanation = ""
    elif len(selected) == 1:
        explanation = selected[0].reason
    else:
        explanation = " ".join(op.reason for op in selected)

    return BlockDecisionResult(
        operations=selected,
        cognitive_state=cognitive_state,
        explanation=explanation,
        intervention_ids=intervention_ids,
    )
