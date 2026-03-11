"""Agent registry — maps intents to specialist agents (Phase 2: 3 agents).

Extracted from orchestrator.py to break circular import risks and
keep agent registration separate from orchestration logic.
"""

import uuid

from services.agent.state import AgentContext, IntentType
from services.agent.base import BaseAgent
from services.agent.agents.tutor import TutorAgent
from services.agent.agents.planner import PlanAgent
from services.agent.agents.layout import LayoutAgent
from services.agent.agents.onboarding import OnboardingAgent


AGENT_REGISTRY: dict[str, BaseAgent] = {
    "tutor": TutorAgent(),
    "planner": PlanAgent(),
    "layout": LayoutAgent(),
    "onboarding": OnboardingAgent(),
}

# Intent -> Agent mapping (Phase 2: 5 intents -> 4 agents)
INTENT_AGENT_MAP: dict[IntentType, str] = {
    IntentType.LEARN: "tutor",
    IntentType.PLAN: "planner",
    IntentType.LAYOUT: "layout",
    IntentType.GENERAL: "tutor",
    IntentType.ONBOARDING: "onboarding",
}


def get_agent(intent: IntentType) -> BaseAgent:
    """Resolve intent to specialist agent."""
    agent_name = INTENT_AGENT_MAP.get(intent, "tutor")
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
    learning_mode: str | None = None,
    block_types: list[str] | None = None,
    dismissed_block_types: list[str] | None = None,
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
        learning_mode=learning_mode,
    )
    if scene:
        ctx.scene = scene
    if block_types:
        ctx.metadata["block_types"] = block_types
    if dismissed_block_types:
        ctx.metadata["dismissed_block_types"] = dismissed_block_types
    return ctx
