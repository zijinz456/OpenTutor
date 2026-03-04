"""Swarm routing detection, parallel execution patterns, and result merging.

Detects when a user request benefits from multiple specialist agents
running in parallel, returns a SwarmPlan describing the fan-out,
and merges results using configurable strategies.
"""

import copy
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from services.agent.state import AgentContext, IntentType

logger = logging.getLogger(__name__)


# ── SwarmPlan ──

@dataclass
class SwarmPlan:
    """Description of a parallel agent dispatch plan."""

    agents: list[dict] = field(default_factory=list)
    # Each entry: {"agent": str, "message": str, "role": str}

    merge_strategy: str = "llm_synthesize"
    # "concatenate" | "llm_synthesize" | "structured"

    reason: str = ""
    primary_agent: str = ""


# ── Predefined Swarm Patterns ──

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
    """Detect whether the user request warrants parallel agent execution."""
    from config import settings

    if not settings.swarm_enabled:
        return None

    message = ctx.user_message
    if not message or len(message.strip()) < 3:
        return None

    matched_pattern: str | None = None

    if ctx.intent == IntentType.PLAN and _EXAM_KEYWORDS.search(message):
        matched_pattern = "exam_prep_comprehensive"
    elif ctx.intent in (IntentType.LEARN, IntentType.GENERAL) and _PRACTICE_KEYWORDS.search(message):
        matched_pattern = "learn_and_practice"
    elif ctx.intent == IntentType.REVIEW and _NEXT_STEP_KEYWORDS.search(message):
        if ctx.scene == "review_drill" or _NEXT_STEP_KEYWORDS.search(message):
            matched_pattern = "review_and_plan"

    if matched_pattern is None:
        return None

    pattern = copy.deepcopy(SWARM_PATTERNS[matched_pattern])
    for agent_spec in pattern["agents"]:
        agent_spec["message"] = agent_spec["message"].replace("{user_message}", message)

    plan = SwarmPlan(
        agents=pattern["agents"],
        merge_strategy=pattern["merge_strategy"],
        reason=pattern["reason"],
        primary_agent=pattern["primary_agent"],
    )

    logger.info(
        "Swarm pattern matched: '%s' for intent=%s, agents=%s",
        matched_pattern, ctx.intent.value, [a["agent"] for a in plan.agents],
    )
    return plan


# ── Merge Strategies ──

ROLE_HEADERS: dict[str, str] = {
    "teaching": "## Explanation",
    "exercise": "## Practice",
    "planning": "## Study Plan",
    "review": "## Review & Analysis",
    "assessment": "## Assessment",
    "curriculum": "## Curriculum Overview",
    "motivation": "## Encouragement",
    "code_execution": "## Code",
    "preference": "## Preferences",
    "scene": "## Scene",
}

_SYNTHESIZE_SYSTEM_PROMPT = (
    "You are an expert educational content editor. Your job is to merge "
    "multiple specialist agent outputs into ONE coherent, well-structured "
    "response for a student. Requirements:\n"
    "- Maintain a natural, conversational tone appropriate for tutoring.\n"
    "- Preserve ALL substantive content from each agent.\n"
    "- Use clear section headers (##) to organize different aspects.\n"
    "- Ensure smooth transitions between sections.\n"
    "- Remove redundancy but keep unique insights from each agent.\n"
    "- If agents provide conflicting information, include both perspectives "
    "with a note.\n"
    "- The final output should read as if written by a single knowledgeable "
    "tutor, not as separate disconnected blocks.\n"
    "- Respond in the same language as the student's original message."
)


async def merge_results(
    results: list[dict],
    user_message: str,
    strategy: str = "llm_synthesize",
    primary_agent: str | None = None,
) -> str:
    """Merge multiple agent results into a single response."""
    successful = [
        r for r in results
        if r.get("success") and r.get("response", "").strip()
    ]

    if not successful:
        logger.warning("No successful results to merge")
        return "[All parallel agents failed to produce a response.]"

    if len(successful) == 1:
        return successful[0]["response"]

    if primary_agent:
        successful.sort(key=lambda r: (0 if r["agent"] == primary_agent else 1))

    if strategy == "concatenate":
        return _merge_concatenate(successful)
    elif strategy == "llm_synthesize":
        return await _merge_llm_synthesize(successful, user_message)
    elif strategy == "structured":
        return _merge_structured(successful)
    else:
        logger.warning("Unknown merge strategy '%s', falling back to concatenate", strategy)
        return _merge_concatenate(successful)


def _merge_concatenate(results: list[dict]) -> str:
    sections: list[str] = []
    for r in results:
        header = ROLE_HEADERS.get(r["agent"], f"## {r['agent'].replace('_', ' ').title()}")
        sections.append(f"{header}\n\n{r['response'].strip()}")
    return "\n\n---\n\n".join(sections)


async def _merge_llm_synthesize(results: list[dict], user_message: str) -> str:
    agent_sections = [
        f"### Agent: {r['agent']} ({ROLE_HEADERS.get(r['agent'], r['agent'].title())})\n{r['response']}"
        for r in results
    ]

    user_prompt = (
        f"Student's original question:\n\"{user_message}\"\n\n"
        f"Below are outputs from {len(results)} specialist agents. "
        f"Merge them into ONE coherent, well-structured response.\n\n"
        + "\n\n---\n\n".join(agent_sections)
    )

    try:
        from services.llm.router import get_llm_client
        client = get_llm_client("small")
        merged_response, usage = await client.extract(_SYNTHESIZE_SYSTEM_PROMPT, user_prompt)
        merged_response = merged_response.strip()

        if merged_response and len(merged_response) > 20:
            logger.info(
                "LLM synthesis merge complete: %d agents -> %d chars (tokens: %s)",
                len(results), len(merged_response), usage,
            )
            return merged_response
        else:
            logger.warning("LLM synthesis returned empty/short result, falling back to concatenate")
            return _merge_concatenate(results)
    except Exception as e:
        logger.warning("LLM synthesis merge failed, falling back to concatenate: %s", e)
        return _merge_concatenate(results)


def _merge_structured(results: list[dict]) -> str:
    merged: dict[str, Any] = {}
    all_json = True

    for r in results:
        try:
            merged[r["agent"]] = json.loads(r["response"].strip())
        except (json.JSONDecodeError, TypeError):
            all_json = False
            break

    if all_json and merged:
        try:
            return json.dumps(merged, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            pass

    return _merge_concatenate(results)
