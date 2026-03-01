"""Agent registry — maps intents to specialist agents.

Extracted from orchestrator.py to break circular import risks and
keep agent registration separate from orchestration logic.
"""

import uuid

from services.agent.state import AgentContext, IntentType
from services.agent.base import BaseAgent
from services.agent.teaching import TeachingAgent
from services.agent.exercise import ExerciseAgent
from services.agent.planning import PlanningAgent
from services.agent.review import ReviewAgent
from services.agent.preference_agent import PreferenceAgent
from services.agent.scene_agent import SceneAgent
from services.agent.code_execution import CodeExecutionAgent
from services.agent.curriculum import CurriculumAgent
from services.agent.assessment import AssessmentAgent
from services.agent.motivation import MotivationAgent


AGENT_REGISTRY: dict[str, BaseAgent] = {
    "teaching": TeachingAgent(),
    "exercise": ExerciseAgent(),
    "planning": PlanningAgent(),
    "review": ReviewAgent(),
    "preference": PreferenceAgent(),
    "scene": SceneAgent(),
    "code_execution": CodeExecutionAgent(),
    "curriculum": CurriculumAgent(),
    "assessment": AssessmentAgent(),
    "motivation": MotivationAgent(),
}

# Intent → Agent mapping (OpenClaw binding pattern)
INTENT_AGENT_MAP: dict[IntentType, str] = {
    IntentType.LEARN: "teaching",
    IntentType.QUIZ: "exercise",
    IntentType.PLAN: "planning",
    IntentType.REVIEW: "review",
    IntentType.PREFERENCE: "preference",
    IntentType.LAYOUT: "preference",
    IntentType.GENERAL: "teaching",
    IntentType.SCENE_SWITCH: "scene",
    IntentType.CODE: "code_execution",
    IntentType.CURRICULUM: "curriculum",
    IntentType.ASSESS: "assessment",
}


def get_agent(intent: IntentType) -> BaseAgent:
    """Resolve intent to specialist agent (OpenClaw binding resolution)."""
    agent_name = INTENT_AGENT_MAP.get(intent, "teaching")
    return AGENT_REGISTRY[agent_name]


def build_agent_context(
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    message: str,
    conversation_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    history: list[dict] | None = None,
    active_tab: str = "",
    tab_context: dict | None = None,
    scene: str | None = None,
    images: list[dict] | None = None,
) -> AgentContext:
    """Create a normalized AgentContext for chat or workflow entry points."""
    ctx = AgentContext(
        user_id=user_id,
        course_id=course_id,
        user_message=message,
        conversation_id=conversation_id,
        session_id=session_id or uuid.uuid4(),
        conversation_history=(history or [])[-10:],
        active_tab=active_tab,
        tab_context=tab_context or {},
        images=images or [],
    )
    if scene:
        ctx.scene = scene
    return ctx
