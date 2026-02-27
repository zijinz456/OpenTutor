"""Agent state machine and session management.

Borrows from:
- OpenAkita AgentState: IDLE → REASONING → ACTING → OBSERVING → VERIFYING
- OpenClaw SessionEntry: token tracking, compaction, model override, abort recovery
- OpenClaw Session Scope: per-course / per-session / per-tab isolation
"""

import uuid
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class TaskPhase(str, Enum):
    """Agent execution phase (OpenAkita TaskState pattern)."""
    IDLE = "idle"
    ROUTING = "routing"           # Orchestrator determining intent
    LOADING_CONTEXT = "loading"   # Fetching preferences, memories, content
    REASONING = "reasoning"       # LLM generating response
    ACTING = "acting"             # Executing tools / actions
    OBSERVING = "observing"       # Processing tool results
    VERIFYING = "verifying"       # Self-check (ReflectionAgent)
    STREAMING = "streaming"       # SSE streaming to client
    POST_PROCESSING = "post"      # Signal extraction, memory encoding
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class IntentType(str, Enum):
    """Classified user intent (v3: 4 categories + layout + general + new agents)."""
    LEARN = "learn"               # Knowledge question → TeachingAgent
    QUIZ = "quiz"                 # Generate quiz → ExerciseAgent
    PLAN = "plan"                 # Study plan → PlanningAgent
    REVIEW = "review"             # Error analysis, review → ReviewAgent
    PREFERENCE = "preference"     # Preference change → PreferenceAgent
    GENERAL = "general"           # General chat → TeachingAgent (fallback)
    LAYOUT = "layout"             # UI layout change → direct action
    SCENE_SWITCH = "scene_switch" # v3: Scene change signal → SceneAgent
    CODE = "code"                 # Code execution → CodeExecutionAgent
    CURRICULUM = "curriculum"     # Course structure analysis → CurriculumAgent
    ASSESS = "assess"             # Learning assessment → AssessmentAgent


@dataclass
class AgentContext:
    """Shared context passed between orchestrator and specialist agents.

    Combines OpenClaw SessionEntry concepts with OpenTutor's domain context.
    """
    # Identity
    user_id: uuid.UUID
    course_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)

    # Input
    user_message: str = ""
    conversation_history: list[dict] = field(default_factory=list)

    # Tab / Scene context (v3)
    active_tab: str = ""
    tab_context: dict = field(default_factory=dict)

    # Routing
    intent: IntentType = IntentType.GENERAL
    intent_confidence: float = 0.0
    scene: str = "study_session"

    # Context data (populated by context loading phase)
    preferences: dict[str, str] = field(default_factory=dict)
    preference_sources: dict[str, str] = field(default_factory=dict)
    content_docs: list[dict] = field(default_factory=list)
    memories: list[dict] = field(default_factory=list)

    # Execution state (OpenAkita TaskState pattern)
    phase: TaskPhase = TaskPhase.IDLE
    phase_history: list[tuple[TaskPhase, float]] = field(default_factory=list)
    delegated_agent: str | None = None

    # Output
    response: str = ""
    actions: list[dict] = field(default_factory=list)
    extracted_signal: dict | None = None

    # Token tracking (OpenClaw SessionEntry pattern)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    # Metadata
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def transition(self, new_phase: TaskPhase):
        """State transition with history tracking."""
        old_phase = self.phase
        self.phase_history.append((old_phase, time.time()))
        self.phase = new_phase
        logger.debug(
            "Agent state: %s → %s (session=%s, agent=%s)",
            old_phase.value, new_phase.value, self.session_id, self.delegated_agent,
        )

    def mark_completed(self):
        self.completed_at = time.time()
        self.transition(TaskPhase.COMPLETED)

    def mark_failed(self, error: str):
        self.error = error
        self.completed_at = time.time()
        self.transition(TaskPhase.FAILED)

    @property
    def duration_ms(self) -> float | None:
        if self.completed_at:
            return (self.completed_at - self.created_at) * 1000
        return None

    def to_status_dict(self) -> dict:
        """Serializable status for frontend progress display."""
        return {
            "session_id": str(self.session_id),
            "phase": self.phase.value,
            "intent": self.intent.value,
            "delegated_agent": self.delegated_agent,
            "duration_ms": self.duration_ms,
            "tokens": self.total_tokens,
            "error": self.error,
        }
