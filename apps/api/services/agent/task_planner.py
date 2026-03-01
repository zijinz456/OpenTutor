"""Multi-step task planner for complex user requests.

Decomposes complex educational goals into sequenced sub-tasks, each
mapped to a specialist agent.  The plan is stored in AgentTask.input_json
and executed step-by-step by the activity engine.

Example: "Help me prepare for my exam next week"
  → [check_progress, identify_weak_points, generate_exercises, schedule_reviews]
"""

import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

# Known step types and their descriptions
STEP_TYPES = {
    "check_progress": "Review current mastery and study metrics",
    "identify_weak_points": "Analyse gap types and low-mastery knowledge points",
    "generate_exercises": "Create targeted practice problems",
    "schedule_reviews": "Plan spaced repetition review sessions",
    "summarize_content": "Generate study notes or summaries",
    "create_flashcards": "Generate flashcards for key concepts",
    "build_study_plan": "Create a time-bound study plan",
    "review_wrong_answers": "Analyse error patterns from wrong answers",
    "assess_readiness": "Evaluate overall exam readiness",
}


@dataclass
class PlanStep:
    """A single step in a multi-step plan."""
    step_index: int
    step_type: str
    title: str
    description: str
    agent: str  # target specialist agent name
    input_params: dict  # parameters passed to the agent/tool
    depends_on: list[int]  # indices of prerequisite steps
    status: str = "pending"  # pending | running | completed | failed | skipped


def _build_planning_prompt(user_message: str, mastery_summary: str | None = None) -> str:
    """Build the LLM prompt for plan decomposition."""
    step_list = "\n".join(f"- {k}: {v}" for k, v in STEP_TYPES.items())
    mastery_section = ""
    if mastery_summary:
        mastery_section = f"\n\nCurrent student status:\n{mastery_summary}"

    return f"""You are a learning plan architect. Decompose the student's request into 2-6 concrete steps.

Available step types:
{step_list}

Each step must specify:
- step_type: one of the available types above
- title: short human-readable title
- description: what this step does
- agent: which specialist handles it (teaching|exercise|planning|review|assessment|curriculum)
- depends_on: list of step indices this step waits for ([] for no dependencies)
{mastery_section}

Student request: "{user_message}"

Return ONLY a JSON array of step objects. Example:
[
  {{"step_type": "check_progress", "title": "Check current progress", "description": "Review mastery scores and identify gaps", "agent": "assessment", "depends_on": []}},
  {{"step_type": "identify_weak_points", "title": "Find weak areas", "description": "Identify knowledge points below 50% mastery", "agent": "assessment", "depends_on": [0]}},
  {{"step_type": "generate_exercises", "title": "Create practice set", "description": "Generate targeted exercises for weak areas", "agent": "exercise", "depends_on": [1]}}
]"""


async def create_plan(
    user_message: str,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    mastery_summary: str | None = None,
) -> list[dict]:
    """Use LLM to decompose a complex request into a multi-step plan."""
    client = get_llm_client()
    prompt = _build_planning_prompt(user_message, mastery_summary)

    response, _ = await client.chat(
        "You are a task planning assistant. Output valid JSON arrays only.",
        prompt,
    )

    try:
        steps = json.loads(response)
    except json.JSONDecodeError:
        # Try to extract JSON from response
        start = response.find("[")
        end = response.rfind("]")
        if start != -1 and end != -1:
            try:
                steps = json.loads(response[start:end + 1])
            except json.JSONDecodeError:
                steps = _fallback_plan(user_message)
        else:
            steps = _fallback_plan(user_message)

    # Validate and normalise steps
    validated = []
    for i, step in enumerate(steps[:6]):  # Max 6 steps
        validated.append({
            "step_index": i,
            "step_type": step.get("step_type", "check_progress"),
            "title": step.get("title", f"Step {i + 1}"),
            "description": step.get("description", ""),
            "agent": step.get("agent", "teaching"),
            "depends_on": step.get("depends_on", []),
            "status": "pending",
            "input_params": {
                "user_id": str(user_id),
                "course_id": str(course_id),
            },
        })

    return validated


def _fallback_plan(user_message: str) -> list[dict]:
    """Simple fallback plan when LLM decomposition fails."""
    return [
        {
            "step_type": "check_progress",
            "title": "Review current progress",
            "description": "Check mastery scores and study metrics",
            "agent": "assessment",
            "depends_on": [],
        },
        {
            "step_type": "identify_weak_points",
            "title": "Identify areas for improvement",
            "description": "Find knowledge gaps based on quiz performance",
            "agent": "assessment",
            "depends_on": [0],
        },
        {
            "step_type": "build_study_plan",
            "title": "Create study plan",
            "description": f"Build a plan addressing: {user_message[:200]}",
            "agent": "planning",
            "depends_on": [1],
        },
    ]


async def execute_plan_step(
    step: dict,
    previous_results: list[dict],
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    db: AsyncSession,
    db_factory,
) -> dict:
    """Execute a single plan step using the appropriate agent.

    Returns a result dict with structured execution metadata for persistence.
    """
    step_type = step["step_type"]

    # Build a context for the sub-agent
    context_message = _build_step_message(step, previous_results)

    try:
        from services.agent.orchestrator import run_agent_turn

        history = [
            {
                "role": "assistant",
                "content": prev["summary"],
            }
            for prev in previous_results
            if prev.get("success") and prev.get("summary")
        ]
        ctx = await run_agent_turn(
            user_id=user_id,
            course_id=course_id,
            message=context_message,
            db=db,
            db_factory=db_factory,
            history=history,
        )
        success = ctx.phase.value != "failed" and not ctx.error and bool(ctx.response.strip())
        envelope = ctx.metadata.get("turn_envelope") if isinstance(ctx.metadata.get("turn_envelope"), dict) else None
        verifier = envelope.get("verifier") if envelope else ctx.metadata.get("verifier")
        provenance = envelope.get("provenance") if envelope else ctx.metadata.get("provenance")
        tool_calls = envelope.get("tool_calls") if envelope else ctx.tool_calls
        return {
            "step_index": step["step_index"],
            "step_type": step_type,
            "title": step.get("title", f"Step {step['step_index'] + 1}"),
            "agent": ctx.delegated_agent,
            "intent": ctx.intent.value,
            "success": success,
            "input_message": context_message,
            "tool_calls": tool_calls if isinstance(tool_calls, list) else [],
            "output": ctx.response[:2000],
            "raw_output": ctx.response,
            "summary": (ctx.response or ctx.error or "Step completed.")[:300],
            "error": ctx.error,
            "verifier": verifier if isinstance(verifier, dict) else None,
            "provenance": provenance if isinstance(provenance, dict) else None,
        }
    except Exception as e:
        logger.error("Plan step %s failed: %s", step_type, e)
        return {
            "step_index": step["step_index"],
            "step_type": step_type,
            "title": step.get("title", f"Step {step['step_index'] + 1}"),
            "success": False,
            "input_message": context_message,
            "tool_calls": [],
            "output": "",
            "raw_output": "",
            "summary": f"Step failed: {e}",
            "error": str(e),
            "verifier": None,
            "provenance": None,
        }


def _build_step_message(step: dict, previous_results: list[dict]) -> str:
    """Build the user message for a plan step, incorporating prior step results."""
    parts = [step.get("description", step.get("title", ""))]

    # Include relevant previous results
    depends_on = step.get("depends_on", [])
    for prev in previous_results:
        if prev["step_index"] in depends_on and prev.get("success"):
            parts.append(f"\nPrevious step ({prev['step_type']}) found:\n{prev['summary']}")

    return "\n".join(parts)


def is_complex_request(user_message: str) -> bool:
    """Heuristic to detect if a request needs multi-step planning.

    Returns True for requests that mention:
    - Exam/test preparation
    - Multiple learning goals
    - Study plans or schedules
    - Comprehensive review
    """
    import re

    complex_patterns = [
        r"(prepare|get\s+ready|review)\s+.*(test|exam|quiz)",
        r"(prepare|study)\s+(for|plan)",
        r"help\s+me\s+(create|make|plan|schedule)\s+.*(plan|schedule)",
        r"(comprehensive|complete|full)\s+(review|study|prep)",
        r"(from\s+scratch|systematic(ally)?)\s+.*(learn|study|review)",
        r"(all|every|each)\s+(chapter|topic|concept)",
        r"(weak|gap)\s+.*(improve|strengthen)",
    ]
    msg_lower = user_message.lower()
    return any(re.search(p, msg_lower) for p in complex_patterns)
