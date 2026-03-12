"""Socratic questioning engine — stateful pedagogical interaction.

Instead of putting "use Socratic method" in a prompt, this module implements
a real finite-state machine that tracks where the student is in understanding
and generates targeted teaching directives for the LLM.

States:
  PROBE    - Ask what the student thinks (open-ended)
  CLARIFY  - Student gave partial/vague answer -> narrow the question
  CONFRONT - Student has misconception -> present counterexample
  SCAFFOLD - Student is stuck -> give hint, not answer
  CONFIRM  - Student got it -> verify with transfer question

Transitions are driven by:
  - Error classification (conceptual -> CONFRONT, procedural -> SCAFFOLD)
  - Cognitive load (high -> skip PROBE, go to SCAFFOLD)
  - Mastery level (low -> more SCAFFOLD, high -> more PROBE)

State is persisted in agent_kv per user+course.
"""

import logging
import uuid
from enum import Enum

logger = logging.getLogger(__name__)


class SocraticState(str, Enum):
    PROBE = "probe"
    CLARIFY = "clarify"
    CONFRONT = "confront"
    SCAFFOLD = "scaffold"
    CONFIRM = "confirm"


# State transition table: (current_state, response_quality) -> next_state
_TRANSITIONS: dict[tuple[SocraticState, str], SocraticState] = {
    # PROBE: open-ended question asked
    (SocraticState.PROBE, "correct"): SocraticState.CONFIRM,
    (SocraticState.PROBE, "partial"): SocraticState.CLARIFY,
    (SocraticState.PROBE, "wrong"): SocraticState.CONFRONT,
    (SocraticState.PROBE, "confused"): SocraticState.SCAFFOLD,
    (SocraticState.PROBE, "no_response"): SocraticState.SCAFFOLD,
    # CLARIFY: narrowing question asked
    (SocraticState.CLARIFY, "correct"): SocraticState.CONFIRM,
    (SocraticState.CLARIFY, "partial"): SocraticState.SCAFFOLD,
    (SocraticState.CLARIFY, "wrong"): SocraticState.CONFRONT,
    (SocraticState.CLARIFY, "confused"): SocraticState.SCAFFOLD,
    (SocraticState.CLARIFY, "no_response"): SocraticState.SCAFFOLD,
    # CONFRONT: counterexample presented
    (SocraticState.CONFRONT, "correct"): SocraticState.CONFIRM,
    (SocraticState.CONFRONT, "partial"): SocraticState.CLARIFY,
    (SocraticState.CONFRONT, "wrong"): SocraticState.SCAFFOLD,
    (SocraticState.CONFRONT, "confused"): SocraticState.SCAFFOLD,
    (SocraticState.CONFRONT, "no_response"): SocraticState.SCAFFOLD,
    # SCAFFOLD: hint given
    (SocraticState.SCAFFOLD, "correct"): SocraticState.PROBE,
    (SocraticState.SCAFFOLD, "partial"): SocraticState.CLARIFY,
    (SocraticState.SCAFFOLD, "wrong"): SocraticState.SCAFFOLD,
    (SocraticState.SCAFFOLD, "confused"): SocraticState.SCAFFOLD,
    (SocraticState.SCAFFOLD, "no_response"): SocraticState.SCAFFOLD,
    # CONFIRM: transfer question asked
    (SocraticState.CONFIRM, "correct"): SocraticState.PROBE,
    (SocraticState.CONFIRM, "partial"): SocraticState.CLARIFY,
    (SocraticState.CONFIRM, "wrong"): SocraticState.CLARIFY,
    (SocraticState.CONFIRM, "confused"): SocraticState.SCAFFOLD,
    (SocraticState.CONFIRM, "no_response"): SocraticState.SCAFFOLD,
}

# Prompt directives per state
_DIRECTIVES: dict[SocraticState, str] = {
    SocraticState.PROBE: (
        "Ask the student an open-ended question about this concept. "
        "Do NOT give the answer. Let them reason. "
        "Example: 'What do you think happens when...?'"
    ),
    SocraticState.CLARIFY: (
        "The student's understanding is vague. Ask a more specific question "
        "to pinpoint what they do and don't understand. "
        "Example: 'When you say X, do you mean A or B?'"
    ),
    SocraticState.CONFRONT: (
        "The student has a misconception. Present a counterexample "
        "that challenges their current understanding. "
        "Do NOT say 'you're wrong'. Let the counterexample create cognitive conflict. "
        "Example: 'If that were true, what would happen in this case...?'"
    ),
    SocraticState.SCAFFOLD: (
        "The student needs help. Give ONE small hint that moves them forward "
        "without giving the full answer. Break the problem into a smaller step. "
        "Example: 'Let's start with just the first part. What is X?'"
    ),
    SocraticState.CONFIRM: (
        "The student seems to understand. Verify with a transfer question — "
        "ask them to apply the same concept in a slightly different context. "
        "Example: 'Good! Now what if we change X to Y?'"
    ),
}

# Maximum turns in SCAFFOLD before giving up and providing direct explanation
_MAX_SCAFFOLD_TURNS = 4


class SocraticEngine:
    """Stateful Socratic teaching strategy engine."""

    def __init__(
        self,
        mastery: float = 0.5,
        cognitive_load: float = 0.0,
        error_type: str | None = None,
        state: SocraticState | None = None,
        turns_in_state: int = 0,
    ):
        self.mastery = mastery
        self.cognitive_load = cognitive_load
        self.error_type = error_type
        self.turns_in_state = turns_in_state

        if state is not None:
            self.state = state
        else:
            self.state = self._initial_state()

    def _initial_state(self) -> SocraticState:
        """Determine starting state based on student context."""
        if self.cognitive_load > 0.7:
            return SocraticState.SCAFFOLD
        if self.mastery < 0.3:
            return SocraticState.SCAFFOLD
        if self.mastery > 0.7:
            return SocraticState.PROBE
        if self.error_type == "conceptual":
            return SocraticState.CONFRONT
        if self.error_type in ("procedural", "computational"):
            return SocraticState.SCAFFOLD
        return SocraticState.CLARIFY

    def transition(self, response_quality: str) -> SocraticState:
        """Advance the state machine based on student response quality.

        Args:
            response_quality: One of "correct", "partial", "wrong", "confused", "no_response"
        """
        new_state = _TRANSITIONS.get(
            (self.state, response_quality),
            SocraticState.SCAFFOLD,
        )

        if new_state == self.state:
            self.turns_in_state += 1
        else:
            self.turns_in_state = 0
            self.state = new_state

        return self.state

    def get_prompt_directive(self) -> str:
        """Generate the teaching instruction for the LLM based on current state."""
        directive = _DIRECTIVES[self.state]

        # Escape hatch: too many scaffold turns means direct explanation is needed
        if self.state == SocraticState.SCAFFOLD and self.turns_in_state >= _MAX_SCAFFOLD_TURNS:
            directive = (
                "The student has been struggling for several turns. "
                "Provide a clear, direct explanation with a worked example. "
                "Then ask a simple verification question to check understanding."
            )

        return f"\n## Teaching Strategy: {self.state.value.upper()}\n{directive}"

    def to_dict(self) -> dict:
        """Serialize for storage in agent_kv."""
        return {
            "state": self.state.value,
            "turns_in_state": self.turns_in_state,
            "mastery": self.mastery,
            "cognitive_load": self.cognitive_load,
            "error_type": self.error_type,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SocraticEngine":
        """Restore from agent_kv storage."""
        state_str = data.get("state")
        state = SocraticState(state_str) if state_str else None
        return cls(
            mastery=data.get("mastery", 0.5),
            cognitive_load=data.get("cognitive_load", 0.0),
            error_type=data.get("error_type"),
            state=state,
            turns_in_state=data.get("turns_in_state", 0),
        )


# ── Persistence helpers ──

SOCRATIC_NAMESPACE = "socratic"
SOCRATIC_KEY = "engine_state"


async def load_socratic_engine(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    mastery: float = 0.5,
    cognitive_load: float = 0.0,
    error_type: str | None = None,
) -> SocraticEngine:
    """Load persisted Socratic state or create new engine."""
    try:
        from services.agent.kv_store import kv_get
        data = await kv_get(db, user_id, SOCRATIC_NAMESPACE, SOCRATIC_KEY, course_id=course_id)
        if data and isinstance(data, dict):
            engine = SocraticEngine.from_dict(data)
            # Update context signals (they change each turn)
            engine.mastery = mastery
            engine.cognitive_load = cognitive_load
            engine.error_type = error_type
            return engine
    except (ConnectionError, TimeoutError, KeyError, ValueError):
        logger.debug("Could not load persisted Socratic state, creating fresh engine")

    return SocraticEngine(
        mastery=mastery,
        cognitive_load=cognitive_load,
        error_type=error_type,
    )


async def save_socratic_engine(
    db,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    engine: SocraticEngine,
) -> None:
    """Persist Socratic state to agent_kv."""
    try:
        from services.agent.kv_store import kv_set
        await kv_set(
            db, user_id, SOCRATIC_NAMESPACE, SOCRATIC_KEY,
            engine.to_dict(), course_id=course_id,
        )
    except (ConnectionError, TimeoutError, KeyError, ValueError) as e:
        logger.debug("Failed to save Socratic state: %s", e)


# ── Response quality classification ──

_QUALITY_PROMPT = """Classify the student's response quality in this tutoring exchange.

Tutor's question/instruction: {tutor_message}
Student's response: {student_message}

Classify as exactly ONE of:
- correct: Student demonstrates understanding, answers correctly
- partial: Student has some understanding but answer is incomplete or vague
- wrong: Student gives an incorrect answer or shows misconception
- confused: Student explicitly expresses confusion or asks for help
- no_response: Student changes topic, gives irrelevant answer, or says very little

Output ONLY one word: correct, partial, wrong, confused, or no_response"""


async def classify_response_quality(
    tutor_message: str,
    student_message: str,
) -> str:
    """Classify student response quality using lightweight LLM call."""
    try:
        from services.llm.router import get_llm_client
        client = get_llm_client("fast")
        result, _ = await client.extract(
            "You are a teaching assessment expert. Output only one word.",
            _QUALITY_PROMPT.format(
                tutor_message=tutor_message[:500],
                student_message=student_message[:500],
            ),
        )
        words = result.strip().lower().split() if result else []
        quality = words[0] if words else "partial"
        valid = {"correct", "partial", "wrong", "confused", "no_response"}
        return quality if quality in valid else "partial"
    except (ConnectionError, TimeoutError, ValueError, RuntimeError):
        logger.debug("Response quality classification failed, defaulting to 'partial'")
        return "partial"
