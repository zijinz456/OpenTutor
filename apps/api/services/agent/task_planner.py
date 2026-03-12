"""Multi-step task planner for complex user requests.

Decomposes complex educational goals into sequenced sub-tasks, each
mapped to a specialist agent.  The plan is stored in AgentTask.input_json
and executed step-by-step by the activity engine.

Example: "Help me prepare for my exam next week"
  → [check_progress, identify_weak_points, generate_exercises, schedule_reviews]
"""

import json
import logging
import re
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

_ACTION_ITEM_RE = re.compile(r"(^|\n)([-*]|\d+\.)\s+\S+")
_TIME_BUCKET_RE = re.compile(r"\b(today|tomorrow|tonight|this week|next week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|daily|weekly)\b", re.IGNORECASE)


def _verifier_allows_step(verifier: dict | None) -> tuple[bool, str | None]:
    if not isinstance(verifier, dict):
        return True, None
    if verifier.get("status") == "failed":
        code = str(verifier.get("code") or "verifier_failed")
        message = str(verifier.get("message") or "The verifier rejected this step output.")
        return False, f"{code}: {message}"
    return True, None


def _step_completion_issue(
    step: dict,
    response: str,
    *,
    tool_calls: list[dict],
    provenance: dict | None,
) -> str | None:
    """Apply lightweight completion checks tailored to the step type."""
    step_type = str(step.get("step_type") or "")
    normalized = (response or "").strip()
    lowered = normalized.lower()
    has_tools = bool(tool_calls)
    content_count = int((provenance or {}).get("content_count") or 0)

    if not normalized:
        return "The step produced no usable output."

    if step_type in {"build_study_plan", "schedule_reviews"}:
        has_actions = bool(_ACTION_ITEM_RE.search(normalized))
        has_time_structure = bool(_TIME_BUCKET_RE.search(lowered))
        if not has_tools and (not has_actions or not has_time_structure):
            return "The step did not produce a time-structured actionable plan."

    if step_type == "generate_exercises":
        mentions_exercises = any(token in lowered for token in ("question", "exercise", "problem", "quiz"))
        if not has_tools and not mentions_exercises:
            return "The step did not produce targeted practice problems."

    if step_type == "create_flashcards":
        mentions_flashcards = any(token in lowered for token in ("flashcard", "flash card", "card"))
        if not has_tools and not mentions_flashcards:
            return "The step did not produce flashcards or a saved flashcard set."

    if step_type == "summarize_content" and len(normalized) < 80:
        return "The summary is too short to be reliable."

    return None


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
  {{"step_type": "check_progress", "title": "Check current progress", "description": "Review mastery scores and identify gaps", "agent": "tutor", "depends_on": []}},
  {{"step_type": "identify_weak_points", "title": "Find weak areas", "description": "Identify knowledge points below 50% mastery", "agent": "tutor", "depends_on": [0]}},
  {{"step_type": "generate_exercises", "title": "Create practice set", "description": "Generate targeted exercises for weak areas", "agent": "tutor", "depends_on": [1]}}
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

    from libs.text_utils import parse_llm_json

    steps = parse_llm_json(response, default=None)
    if not isinstance(steps, list):
        steps = _fallback_plan(user_message)

    # Validate and normalise steps
    validated = []
    for i, step in enumerate(steps[:6]):  # Max 6 steps
        validated.append({
            "step_index": i,
            "step_type": step.get("step_type", "check_progress"),
            "title": step.get("title", f"Step {i + 1}"),
            "description": step.get("description", ""),
            "agent": step.get("agent", "tutor"),
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
            "agent": "tutor",
            "depends_on": [],
        },
        {
            "step_type": "identify_weak_points",
            "title": "Identify areas for improvement",
            "description": "Find knowledge gaps based on quiz performance",
            "agent": "tutor",
            "depends_on": [0],
        },
        {
            "step_type": "build_study_plan",
            "title": "Create study plan",
            "description": f"Build a plan addressing: {user_message[:200]}",
            "agent": "planner",
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
    step_type = step.get("step_type", "unknown")

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
        envelope = ctx.metadata.get("turn_envelope") if isinstance(ctx.metadata.get("turn_envelope"), dict) else None
        verifier = envelope.get("verifier") if envelope else ctx.metadata.get("verifier")
        verifier_diagnostics = envelope.get("verifier_diagnostics") if envelope else ctx.metadata.get("verifier_diagnostics")
        provenance = envelope.get("provenance") if envelope else ctx.metadata.get("provenance")
        tool_calls = envelope.get("tool_calls") if envelope else ctx.tool_calls
        verifier_ok, verifier_issue = _verifier_allows_step(verifier if isinstance(verifier, dict) else None)
        completion_issue = _step_completion_issue(
            step,
            ctx.response,
            tool_calls=tool_calls if isinstance(tool_calls, list) else [],
            provenance=provenance if isinstance(provenance, dict) else None,
        )
        success = (
            ctx.phase.value != "failed"
            and not ctx.error
            and bool(ctx.response.strip())
            and verifier_ok
            and completion_issue is None
        )
        error_message = ctx.error or verifier_issue or completion_issue
        summary = (ctx.response or error_message or "Step completed.")[:300]
        if not success and error_message:
            summary = f"Step failed quality gate: {error_message}"[:300]
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
            "summary": summary,
            "error": error_message,
            "verifier": verifier if isinstance(verifier, dict) else None,
            "verifier_diagnostics": verifier_diagnostics if isinstance(verifier_diagnostics, dict) else None,
            "provenance": provenance if isinstance(provenance, dict) else None,
        }
    except (ConnectionError, TimeoutError, ValueError, RuntimeError, OSError) as e:
        logger.exception("Plan step %s failed: %s", step_type, e)
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
            "verifier_diagnostics": None,
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
