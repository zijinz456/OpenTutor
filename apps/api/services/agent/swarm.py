"""Swarm routing detection and predefined parallel execution patterns.

Detects when a user request benefits from multiple specialist agents
running in parallel, and returns a SwarmPlan describing the fan-out.

Patterns are matched via keyword heuristics against the user message
and the classified intent/scene context.  This avoids
an extra LLM call for pattern detection; only novel multi-agent combos
would need LLM-based planning in the future.
"""

import copy
import logging
import re
from dataclasses import dataclass, field

from services.agent.state import AgentContext, IntentType

logger = logging.getLogger(__name__)


@dataclass
class SwarmPlan:
    """Description of a parallel agent dispatch plan."""

    agents: list[dict] = field(default_factory=list)
    # Each entry: {"agent": str, "message": str, "role": str}

    merge_strategy: str = "llm_synthesize"
    # "concatenate" | "llm_synthesize" | "structured"

    reason: str = ""
    # Human-readable explanation of why swarm was triggered

    primary_agent: str = ""
    # The agent whose output should appear first / receive priority


# ── Predefined Swarm Patterns ──
# Each pattern defines which agents to fan-out, what messages they receive,
# and how to merge the results.  The "{user_message}" placeholder is
# replaced at runtime with the actual user input.

SWARM_PATTERNS: dict[str, dict] = {
    "exam_prep_comprehensive": {
        "agents": [
            {
                "agent": "assessment",
                "message": (
                    "Assess the student's current knowledge level based on their "
                    "request and any available learning history. Provide a brief "
                    "diagnostic summary.\n\nStudent request: {user_message}"
                ),
                "role": "assessor",
            },
            {
                "agent": "exercise",
                "message": (
                    "Generate practice questions targeting likely exam topics based "
                    "on the student's request. Include a mix of difficulty levels.\n\n"
                    "Student request: {user_message}"
                ),
                "role": "practice",
            },
            {
                "agent": "planning",
                "message": (
                    "Create a focused study plan for exam preparation based on the "
                    "student's request. Prioritize high-yield topics and suggest a "
                    "timeline.\n\nStudent request: {user_message}"
                ),
                "role": "planner",
            },
        ],
        "merge_strategy": "llm_synthesize",
        "reason": "Comprehensive exam preparation: assessment + practice + planning",
        "primary_agent": "planning",
    },
    "learn_and_practice": {
        "agents": [
            {
                "agent": "teaching",
                "message": (
                    "Explain the concept clearly and thoroughly based on the "
                    "student's request.\n\nStudent request: {user_message}"
                ),
                "role": "teacher",
            },
            {
                "agent": "exercise",
                "message": (
                    "Generate practice exercises that reinforce the concept the "
                    "student is asking about. Start with easier questions.\n\n"
                    "Student request: {user_message}"
                ),
                "role": "practice",
            },
        ],
        "merge_strategy": "concatenate",
        "reason": "Learn and practice: explanation + exercises in one response",
        "primary_agent": "teaching",
    },
    "review_and_plan": {
        "agents": [
            {
                "agent": "review",
                "message": (
                    "Analyze the student's recent performance and identify areas "
                    "that need improvement.\n\nStudent request: {user_message}"
                ),
                "role": "reviewer",
            },
            {
                "agent": "planning",
                "message": (
                    "Based on the student's request for next steps, create an "
                    "actionable improvement plan.\n\nStudent request: {user_message}"
                ),
                "role": "planner",
            },
        ],
        "merge_strategy": "llm_synthesize",
        "reason": "Review and plan: error analysis + improvement roadmap",
        "primary_agent": "review",
    },
}


# ── Keyword Detection Patterns ──
# Each tuple: (compiled regex, weight) — English keywords

_EXAM_KEYWORDS = re.compile(
    r"(exam|test|final|midterm|prepare\s+for|review\s+plan)",
    re.IGNORECASE,
)

_PRACTICE_KEYWORDS = re.compile(
    r"(practice|quiz|exercise|problem|question|generate\s+questions)",
    re.IGNORECASE,
)

_NEXT_STEP_KEYWORDS = re.compile(
    r"(next\s+step|improve|next|plan|what\s+should\s+i|how\s+to\s+improve)",
    re.IGNORECASE,
)


def should_use_swarm(ctx: AgentContext) -> SwarmPlan | None:
    """Detect whether the user request warrants parallel agent execution.

    Checks intent + message keywords to match predefined swarm patterns.
    Returns a SwarmPlan with templated agent messages, or None if the
    request should be handled by a single agent.

    Pattern matching rules:
    1. PLAN intent + exam-related keywords -> exam_prep_comprehensive
    2. LEARN intent + practice/quiz keywords -> learn_and_practice
    3. REVIEW intent (in review_drill scene) + next-step keywords -> review_and_plan
    """
    from config import settings

    if not settings.swarm_enabled:
        return None

    message = ctx.user_message
    if not message or len(message.strip()) < 3:
        return None

    matched_pattern: str | None = None

    # Pattern 1: Exam prep — PLAN intent + exam keywords
    if ctx.intent == IntentType.PLAN and _EXAM_KEYWORDS.search(message):
        matched_pattern = "exam_prep_comprehensive"

    # Pattern 2: Learn + practice — LEARN/GENERAL intent + practice keywords
    elif ctx.intent in (IntentType.LEARN, IntentType.GENERAL) and _PRACTICE_KEYWORDS.search(message):
        matched_pattern = "learn_and_practice"

    # Pattern 3: Review + plan — REVIEW intent in review_drill scene + next-step keywords
    elif ctx.intent == IntentType.REVIEW and _NEXT_STEP_KEYWORDS.search(message):
        # Particularly strong signal when in review_drill scene
        if ctx.scene == "review_drill" or _NEXT_STEP_KEYWORDS.search(message):
            matched_pattern = "review_and_plan"

    if matched_pattern is None:
        return None

    # Deep-copy the pattern so we don't mutate the template
    pattern = copy.deepcopy(SWARM_PATTERNS[matched_pattern])

    # Template the user message into each agent's message
    for agent_spec in pattern["agents"]:
        agent_spec["message"] = agent_spec["message"].replace(
            "{user_message}", message,
        )

    plan = SwarmPlan(
        agents=pattern["agents"],
        merge_strategy=pattern["merge_strategy"],
        reason=pattern["reason"],
        primary_agent=pattern["primary_agent"],
    )

    logger.info(
        "Swarm pattern matched: '%s' for intent=%s, agents=%s",
        matched_pattern,
        ctx.intent.value,
        [a["agent"] for a in plan.agents],
    )

    return plan
