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
from typing import Any, Callable, Literal

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
    PARALLEL_DISPATCH = "parallel_dispatch"  # Swarm: fan-out to multiple agents
    MERGING = "merging"           # Swarm: merging parallel results
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SceneName(str, Enum):
    """Canonical scene identifiers (v3 preset scenes)."""
    STUDY_SESSION = "study_session"
    EXAM_PREP = "exam_prep"
    ASSIGNMENT = "assignment"
    REVIEW_DRILL = "review_drill"
    NOTE_ORGANIZE = "note_organize"

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._value2member_map_


class IntentType(str, Enum):
    """Classified user intent (Phase 2: consolidated to 4 categories)."""
    LEARN = "learn"       # teach / quiz / review / assess / curriculum
    PLAN = "plan"         # study plan, deadlines
    LAYOUT = "layout"     # UI layout changes
    GENERAL = "general"   # everything else


@dataclass
class InputRequirement:
    """Declares an input that an agent would like answered before execution.

    Inspired by OpenClaw's SKILL.md 'Inputs' section pattern.
    """
    key: str                                        # e.g., "deadline", "difficulty"
    question: str                                   # Human-readable question
    options: list[str]                              # Suggested options for the user
    check: Callable[["AgentContext"], bool]          # Returns True if already satisfied


@dataclass
class AgentContext:
    """Shared context passed between orchestrator and specialist agents.

    Combines OpenClaw SessionEntry concepts with OpenTutor Zenus's domain context.
    """
    # Identity
    user_id: uuid.UUID
    course_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)

    # Input
    user_message: str = ""
    conversation_history: list[dict] = field(default_factory=list)
    images: list[dict] = field(default_factory=list)  # [{"data": base64, "media_type": str}]

    # Tab / Scene context (v3)
    active_tab: str = ""
    tab_context: dict = field(default_factory=dict)

    # Routing
    intent: IntentType = IntentType.GENERAL
    intent_confidence: float = 0.0
    scene: str = SceneName.STUDY_SESSION

    # Context data (populated by context loading phase)
    preferences: dict[str, str] = field(default_factory=dict)
    preference_sources: dict[str, str] = field(default_factory=dict)
    content_docs: list[dict] = field(default_factory=list)
    memories: list[dict] = field(default_factory=list)

    # Adaptive difficulty (populated during context loading for QUIZ intent)
    difficulty_guidance: str | None = None

    # Pre-task clarification (OpenClaw Inputs pattern)
    clarify_inputs: dict[str, str] = field(default_factory=dict)

    # Execution state (OpenAkita TaskState pattern)
    phase: TaskPhase = TaskPhase.IDLE
    phase_history: list[tuple[TaskPhase, float]] = field(default_factory=list)
    delegated_agent: str | None = None

    # Output
    response: str = ""
    actions: list[dict] = field(default_factory=list)
    extracted_signal: dict | None = None

    # ReAct loop tracking
    tool_calls: list[dict] = field(default_factory=list)
    # Each entry: {"tool": str, "input": dict, "output": str, "iteration": int}
    react_iterations: int = 0

    # Tool progress events (consumed by orchestrator for SSE streaming)
    tool_progress: list[dict] = field(default_factory=list)

    # Token tracking (OpenClaw SessionEntry pattern)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    # Tool idempotency cache (used by ToolRegistry to deduplicate calls)
    _idem_cache: dict[str, Any] = field(default_factory=dict)

    # Learning mode (from frontend preferences)
    learning_mode: str | None = None  # course_following, self_paced, exam_prep, maintenance

    # Metadata
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Swarm / parallel execution fields
    parallel_branches: list[dict] = field(default_factory=list)
    swarm_mode: bool = False
    merge_strategy: str = "llm_synthesize"

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

    def emit_progress(self, tool: str, message: str, step: int = 0, total: int = 0):
        """Emit a progress event from a running tool (picked up by orchestrator SSE loop)."""
        self.tool_progress.append({"tool": tool, "message": message, "step": step, "total": total})

    @property
    def duration_ms(self) -> float | None:
        if self.completed_at:
            return (self.completed_at - self.created_at) * 1000
        return None

    def snapshot_for_postprocess(self) -> "AgentContext":
        """Create a lightweight copy for post-processing tasks.

        Avoids deep-copying large fields (conversation_history, content_docs,
        memories, images) that post_process() never reads.
        """
        import copy
        snap = AgentContext(
            user_id=self.user_id,
            course_id=self.course_id,
            conversation_id=self.conversation_id,
            session_id=self.session_id,
            user_message=self.user_message,
            active_tab=self.active_tab,
            intent=self.intent,
            intent_confidence=self.intent_confidence,
            scene=self.scene,
            phase=self.phase,
            delegated_agent=self.delegated_agent,
            response=self.response,
            actions=list(self.actions),
            extracted_signal=self.extracted_signal,
            tool_calls=list(self.tool_calls),
            react_iterations=self.react_iterations,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
            created_at=self.created_at,
            completed_at=self.completed_at,
            error=self.error,
            metadata=copy.copy(self.metadata),
            swarm_mode=self.swarm_mode,
            merge_strategy=self.merge_strategy,
        )
        return snap

    def to_postprocess_payload(self) -> dict[str, Any]:
        """Serialize the minimal context needed for durable post-processing."""
        return {
            "user_id": str(self.user_id),
            "course_id": str(self.course_id),
            "conversation_id": str(self.conversation_id) if self.conversation_id else None,
            "session_id": str(self.session_id),
            "user_message": self.user_message,
            "active_tab": self.active_tab,
            "intent": self.intent.value if self.intent else IntentType.GENERAL.value,
            "intent_confidence": self.intent_confidence,
            "scene": self.scene,
            "phase": self.phase.value if self.phase else TaskPhase.IDLE.value,
            "delegated_agent": self.delegated_agent,
            "response": self.response,
            "actions": list(self.actions),
            "extracted_signal": self.extracted_signal,
            "tool_calls": list(self.tool_calls),
            "react_iterations": self.react_iterations,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "metadata": dict(self.metadata),
            "swarm_mode": self.swarm_mode,
            "merge_strategy": self.merge_strategy,
        }

    @classmethod
    def from_postprocess_payload(cls, payload: dict[str, Any]) -> "AgentContext":
        """Rehydrate a post-process snapshot from a durable task payload."""
        conversation_id = payload.get("conversation_id")
        session_id = payload.get("session_id")
        intent_raw = payload.get("intent") or IntentType.GENERAL.value
        phase_raw = payload.get("phase") or TaskPhase.IDLE.value

        try:
            intent = IntentType(intent_raw)
        except ValueError:
            intent = IntentType.GENERAL

        try:
            phase = TaskPhase(phase_raw)
        except ValueError:
            phase = TaskPhase.IDLE

        return cls(
            user_id=uuid.UUID(str(payload["user_id"])),
            course_id=uuid.UUID(str(payload["course_id"])),
            conversation_id=uuid.UUID(str(conversation_id)) if conversation_id else None,
            session_id=uuid.UUID(str(session_id)) if session_id else uuid.uuid4(),
            user_message=str(payload.get("user_message") or ""),
            active_tab=str(payload.get("active_tab") or ""),
            intent=intent,
            intent_confidence=float(payload.get("intent_confidence") or 0.0),
            scene=payload.get("scene") or SceneName.STUDY_SESSION.value,
            phase=phase,
            delegated_agent=payload.get("delegated_agent"),
            response=str(payload.get("response") or ""),
            actions=list(payload.get("actions") or []),
            extracted_signal=payload.get("extracted_signal"),
            tool_calls=list(payload.get("tool_calls") or []),
            react_iterations=int(payload.get("react_iterations") or 0),
            input_tokens=int(payload.get("input_tokens") or 0),
            output_tokens=int(payload.get("output_tokens") or 0),
            total_tokens=int(payload.get("total_tokens") or 0),
            created_at=float(payload.get("created_at") or time.time()),
            completed_at=payload.get("completed_at"),
            error=payload.get("error"),
            metadata=dict(payload.get("metadata") or {}),
            swarm_mode=bool(payload.get("swarm_mode")),
            merge_strategy=str(payload.get("merge_strategy") or "llm_synthesize"),
        )

    def to_status_dict(self) -> dict:
        """Serializable status for frontend progress display."""
        status = {
            "session_id": str(self.session_id),
            "phase": self.phase.value,
            "intent": self.intent.value,
            "delegated_agent": self.delegated_agent,
            "duration_ms": self.duration_ms,
            "tokens": self.total_tokens,
            "error": self.error,
        }
        if self.swarm_mode:
            status["swarm"] = {
                "enabled": True,
                "merge_strategy": self.merge_strategy,
                "branches": len(self.parallel_branches),
                "successful": sum(
                    1 for b in self.parallel_branches if b.get("success")
                ),
                "agents": [b.get("agent") for b in self.parallel_branches],
            }
        return status


@dataclass
class AgentVerificationResult:
    status: Literal["pass", "repaired", "failed"]
    code: str
    message: str
    repair_attempted: bool = False


@dataclass
class AgentTurnEnvelope:
    response: str
    agent: str
    intent: str
    actions: list[dict]
    tool_calls: list[dict]
    provenance: dict[str, Any]
    verifier: AgentVerificationResult | None
    task_link: dict[str, Any] | None = None
