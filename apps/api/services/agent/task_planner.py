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
) -> dict:
    """Execute a single plan step using the appropriate agent.

    Returns a result dict with {output, summary, success}.
    """
    from services.agent.state import AgentContext, IntentType

    step_type = step["step_type"]
    agent_name = step.get("agent", "teaching")

    # Build a context for the sub-agent
    context_message = _build_step_message(step, previous_results)

    # Map agent name to intent
    agent_intent_map = {
        "teaching": IntentType.LEARN,
        "exercise": IntentType.QUIZ,
        "planning": IntentType.PLAN,
        "review": IntentType.REVIEW,
        "assessment": IntentType.ASSESS,
        "curriculum": IntentType.CURRICULUM,
    }
    intent = agent_intent_map.get(agent_name, IntentType.GENERAL)

    ctx = AgentContext(
        user_id=user_id,
        course_id=course_id,
        user_message=context_message,
        intent=intent,
    )

    # Get the agent and execute
    from services.agent.orchestrator import get_agent
    agent = get_agent(intent)

    try:
        ctx = await agent.run(ctx, db)
        return {
            "step_index": step["step_index"],
            "step_type": step_type,
            "success": True,
            "output": ctx.response[:2000],
            "summary": ctx.response[:300],
        }
    except Exception as e:
        logger.error("Plan step %s failed: %s", step_type, e)
        return {
            "step_index": step["step_index"],
            "step_type": step_type,
            "success": False,
            "output": "",
            "summary": f"Step failed: {e}",
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
        r"(准备|备战|复习).*(考试|测验|test|exam)",
        r"(prepare|study)\s+(for|plan)",
        r"帮我(制定|安排|规划).*(计划|方案|schedule)",
        r"(comprehensive|complete|full)\s+(review|study|prep)",
        r"(从头|系统).*(学|复习|review)",
        r"(all|every|each)\s+(chapter|topic|concept)",
        r"(薄弱|weak|gap).*(提升|improve|strengthen)",
    ]
    msg_lower = user_message.lower()
    return any(re.search(p, msg_lower) for p in complex_patterns)
