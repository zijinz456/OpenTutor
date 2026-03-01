"""Intent router with rule pre-matching + LLM fallback.

Borrows from:
- OpenAkita multi-layer routing: rules first, LLM for ambiguous cases
- OpenClaw binding router: keyword → agent mapping
- Spec Section 2: Intent Router with LEARN / ACTION / PREF classification

Enhancement over original: two-stage routing (regex → LLM) for robustness.
"""

import json
import re
import logging

from services.agent.state import AgentContext, IntentType
from services.llm.router import get_llm_client

logger = logging.getLogger(__name__)

# ── Stage 1: Rule-based pre-matching (high confidence, zero latency) ──

INTENT_RULES: list[tuple[IntentType, re.Pattern, float]] = [
    # Layout actions (highest priority — direct UI control)
    (IntentType.LAYOUT, re.compile(
        r"(layout|resize|maximize|minimize|expand|collapse|"
        r"set_layout|change\s+layout|zoom\s+in|zoom\s+out|fullscreen)", re.IGNORECASE
    ), 0.95),

    # v3: Scene switch signals (high priority — goal/mode change)
    (IntentType.SCENE_SWITCH, re.compile(
        r"(prepare\s+for\s+(an?\s+)?exam|get\s+ready\s+for\s+(an?\s+)?exam|"
        r"exam\s+prep|start\s+review(ing)?|"
        r"do\s+(my\s+)?homework|work\s+on\s+(my\s+)?homework|this\s+assignment|"
        r"homework\s+help|error\s+drill|review\s+mistakes|"
        r"switch\s+to\s+.*mode|organize\s+(my\s+)?notes)", re.IGNORECASE
    ), 0.90),

    # Explicit preference changes
    (IntentType.PREFERENCE, re.compile(
        r"(prefer|switch\s+to|i\s+like|i\s+don'?t\s+like|i\s+prefer|"
        r"change\s+to|too\s+(long|short|detailed|brief)|make\s+it)", re.IGNORECASE
    ), 0.90),

    # Quiz / Exercise
    (IntentType.QUIZ, re.compile(
        r"(quiz|exercise|test\s+me|practice|"
        r"generate\s+(quiz|question|questions|problem|practice\s+questions)|"
        r"generate\s+\d+\s+practice\s+questions|give\s+me\s+(a\s+)?question)", re.IGNORECASE
    ), 0.90),

    # Study plan
    (IntentType.PLAN, re.compile(
        r"(study\s+plan|review\s+schedule|plan\s+for|schedule|"
        r"how\s+should\s+I\s+study|help\s+me\s+plan|study\s+schedule|"
        r"schedule\s+for\s+finals|create\s+a\s+study\s+schedule)", re.IGNORECASE
    ), 0.90),

    # Error review / analysis
    (IntentType.REVIEW, re.compile(
        r"(wrong|mistake|error\s+analysis|review\s+my|"
        r"what\s+did\s+I\s+get\s+wrong|where\s+did\s+I\s+go\s+wrong|"
        r"why\s+(is|was)\s+(it|this)\s+wrong|what\s+went\s+wrong)", re.IGNORECASE
    ), 0.85),

    # Code execution / programming (before LEARN to catch code-related queries first)
    (IntentType.CODE, re.compile(
        r"(run\s+(this|my|the)\s+code|debug|programming|code|```python|"
        r"code\s+execution|write\s+a?\s*program|run\s+this|"
        r"this\s+code|compile)", re.IGNORECASE
    ), 0.90),

    # Course structure / curriculum analysis
    (IntentType.CURRICULUM, re.compile(
        r"(course\s+structure|knowledge\s+graph|outline|syllabus|curriculum|"
        r"prerequisite|topic\s+hierarchy|chapter|learning\s+path|"
        r"dependency|topic\s+relationship)", re.IGNORECASE
    ), 0.85),

    # Learning assessment / progress report
    (IntentType.ASSESS, re.compile(
        r"(assessment|my\s+progress|progress\s+report|report|"
        r"weak\s+area|how\s+am\s+I\s+doing|"
        r"exam\s+readiness|mastery|learning\s+status)", re.IGNORECASE
    ), 0.85),

    # Learning / knowledge questions (broadest, lowest priority)
    (IntentType.LEARN, re.compile(
        r"(explain|what\s+is|how\s+does|why\s+does|define|concept|"
        r"tell\s+me\s+about|help\s+me\s+understand|teach\s+me|"
        r"don'?t\s+understand|clarify)", re.IGNORECASE
    ), 0.80),
]


def rule_match(message: str) -> tuple[IntentType, float] | None:
    """Stage 1: Fast regex-based intent detection.

    Returns (intent, confidence) if a rule matches, else None.
    """
    for intent, pattern, confidence in INTENT_RULES:
        if pattern.search(message):
            return intent, confidence
    return None


# ── Stage 2: LLM classification (for ambiguous cases) ──

CLASSIFICATION_PROMPT = """Classify the student's message into ONE intent category.

Categories:
- learn: Knowledge question, explanation request, concept clarification
- quiz: Request to generate quiz, exercise, practice problems
- plan: Request for study plan, schedule, learning roadmap
- review: Review errors, analyze mistakes, wrong answer analysis
- preference: Change display settings, learning style preference
- layout: Change UI layout (panel sizes, fullscreen)
- scene_switch: Goal/mode change — preparing for exam, starting homework, switching to review mode, organizing notes
- code: Code execution, programming help, debugging, running code snippets
- curriculum: Course structure analysis, knowledge graph, prerequisites, syllabus
- assess: Learning assessment, progress report, mastery check, weak areas
- general: General chat, greeting, off-topic

Output JSON: {{"intent": "<category>", "confidence": <0.0-1.0>}}

Student message: {message}"""


async def llm_classify(message: str) -> tuple[IntentType, float]:
    """Stage 2: LLM-based classification for ambiguous messages."""
    client = get_llm_client()
    try:
        result, _ = await client.extract(
            "You are an intent classifier. Output only valid JSON.",
            CLASSIFICATION_PROMPT.format(message=message[:300]),
        )
        result = result.strip()
        if "```" in result:
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = result[json_start:json_end]

        data = json.loads(result)
        intent_str = data.get("intent", "general")
        confidence = float(data.get("confidence", 0.5))

        try:
            intent = IntentType(intent_str)
        except ValueError:
            intent = IntentType.GENERAL
            confidence = 0.3

        return intent, confidence

    except Exception as e:
        logger.warning("LLM intent classification failed: %s", e)
        return IntentType.GENERAL, 0.3


async def classify_intent(ctx: AgentContext) -> AgentContext:
    """Two-stage intent classification: rules first, LLM fallback.

    Updates ctx.intent and ctx.intent_confidence in-place.
    """
    message = ctx.user_message

    # Stage 1: Rule matching (fast, high precision)
    rule_result = rule_match(message)
    if rule_result:
        intent, confidence = rule_result
        ctx.intent = intent
        ctx.intent_confidence = confidence
        logger.info(
            "Intent classified by RULE: %s (conf=%.2f) msg=%s",
            intent.value, confidence, message[:60],
        )
        return ctx

    # Stage 2: LLM classification (slower, handles ambiguity)
    intent, confidence = await llm_classify(message)
    ctx.intent = intent
    ctx.intent_confidence = confidence
    logger.info(
        "Intent classified by LLM: %s (conf=%.2f) msg=%s",
        intent.value, confidence, message[:60],
    )
    return ctx
