"""Multi-level model routing via complexity scoring.

Inspired by OpenFang's model router. Instead of binary "small"/"large",
we score each request's complexity and route to one of 3 tiers:
  - fast:     Simple queries, greetings, preference changes
  - standard: Teaching, exercises, review — most education tasks
  - frontier: Complex planning, code execution, multi-step reasoning

Scoring uses education-domain heuristics (no LLM call needed).
"""

import re
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ModelTier(str, Enum):
    FAST = "fast"
    STANDARD = "standard"
    FRONTIER = "frontier"


# ── Per-Agent Minimum Tiers ──
# Agents with simple tasks can use fast; complex agents need at least standard.

AGENT_MIN_TIERS: dict[str, ModelTier] = {
    "preference": ModelTier.FAST,
    "scene": ModelTier.FAST,
    "motivation": ModelTier.FAST,
    "teaching": ModelTier.STANDARD,
    "exercise": ModelTier.STANDARD,
    "review": ModelTier.STANDARD,
    "assessment": ModelTier.STANDARD,
    "curriculum": ModelTier.STANDARD,
    "planning": ModelTier.FRONTIER,
    "code_execution": ModelTier.FRONTIER,
}

# ── Complexity Markers ──
# Phrases that indicate higher reasoning complexity

_COMPLEXITY_PATTERNS = [
    (re.compile(r"\bcompare\b", re.IGNORECASE), 30),
    (re.compile(r"\bcontrast\b", re.IGNORECASE), 30),
    (re.compile(r"\bstep[- ]by[- ]step\b", re.IGNORECASE), 40),
    (re.compile(r"\bprove\b", re.IGNORECASE), 50),
    (re.compile(r"\bderive\b", re.IGNORECASE), 40),
    (re.compile(r"\banalyze\b|\banalyse\b", re.IGNORECASE), 30),
    (re.compile(r"\bexplain\s+why\b", re.IGNORECASE), 25),
    (re.compile(r"\bdesign\b", re.IGNORECASE), 35),
    (re.compile(r"\boptimize\b|\boptimise\b", re.IGNORECASE), 40),
    (re.compile(r"\bdebug\b", re.IGNORECASE), 35),
    (re.compile(r"\b(multiple|several)\s+(ways?|methods?|approaches?)\b", re.IGNORECASE), 30),
    # CJK complexity markers
    (re.compile(r"证明|推导"), 50),
    (re.compile(r"比较|对比"), 30),
    (re.compile(r"分析|解析"), 30),
    (re.compile(r"一步一步|逐步"), 40),
    (re.compile(r"优化|改进"), 35),
]

# ── Scoring Thresholds ──

FAST_THRESHOLD = 150      # score < 150 → fast
FRONTIER_THRESHOLD = 500  # score >= 500 → frontier
# 150 <= score < 500 → standard


def _score_message_length(message: str) -> int:
    """Score based on message length (0-150)."""
    length = len(message)
    if length < 20:
        return 0       # Very short (greetings, "ok", etc.)
    if length < 80:
        return 30
    if length < 200:
        return 70
    if length < 500:
        return 100
    return 150         # Long, detailed question


def _score_intent(intent: str) -> int:
    """Score based on classified intent (0-300)."""
    intent_scores = {
        "preference": 30,
        "general": 50,
        "layout": 30,
        "scene_switch": 30,
        "learn": 150,
        "quiz": 180,
        "review": 160,
        "assess": 200,
        "curriculum": 200,
        "plan": 250,
        "code": 250,
    }
    return intent_scores.get(intent, 100)


def _score_scene(scene: str) -> int:
    """Score based on active scene (0-100)."""
    scene_scores = {
        "study_session": 0,
        "review_drill": 40,
        "note_organize": 20,
        "exam_prep": 80,
        "assignment": 60,
    }
    return scene_scores.get(scene, 0)


def _score_conversation_depth(history_length: int) -> int:
    """Score based on conversation depth (0-80)."""
    if history_length <= 4:
        return 0
    extra = min(history_length - 4, 8)  # Cap at 8 extra messages
    return extra * 10


def _score_complexity_markers(message: str) -> int:
    """Score based on complexity-indicating phrases (0-100, capped)."""
    total = 0
    for pattern, points in _COMPLEXITY_PATTERNS:
        if pattern.search(message):
            total += points
    return min(total, 100)


def score_complexity(
    message: str,
    intent: str = "general",
    scene: str = "study_session",
    history_length: int = 0,
    has_rag_context: bool = False,
) -> int:
    """Score the complexity of a request (0-780 range).

    Higher = needs a more capable model.
    """
    score = 0
    score += _score_message_length(message)
    score += _score_intent(intent)
    score += _score_scene(scene)
    score += _score_conversation_depth(history_length)
    score += _score_complexity_markers(message)

    # RAG synthesis bonus: if RAG context is present, model needs to synthesize
    if has_rag_context:
        score += 50

    return score


def resolve_tier(
    agent_name: str,
    message: str = "",
    intent: str = "general",
    scene: str = "study_session",
    history_length: int = 0,
    has_rag_context: bool = False,
) -> ModelTier:
    """Resolve the model tier for a request.

    Returns max(scored_tier, agent_min_tier).
    """
    score = score_complexity(
        message=message,
        intent=intent,
        scene=scene,
        history_length=history_length,
        has_rag_context=has_rag_context,
    )

    if score >= FRONTIER_THRESHOLD:
        scored_tier = ModelTier.FRONTIER
    elif score >= FAST_THRESHOLD:
        scored_tier = ModelTier.STANDARD
    else:
        scored_tier = ModelTier.FAST

    # Agent minimum tier override
    agent_min = AGENT_MIN_TIERS.get(agent_name, ModelTier.STANDARD)

    # Use the higher of the two
    tier_order = {ModelTier.FAST: 0, ModelTier.STANDARD: 1, ModelTier.FRONTIER: 2}
    final_tier = scored_tier if tier_order[scored_tier] >= tier_order[agent_min] else agent_min

    logger.debug(
        "Model routing: agent=%s score=%d scored_tier=%s agent_min=%s → %s",
        agent_name, score, scored_tier.value, agent_min.value, final_tier.value,
    )

    return final_tier
