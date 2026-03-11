"""Intent router with rule-based matching (Phase 2: simplified to 4 intents).

Borrows from:
- OpenAkita multi-layer routing: rules first
- OpenClaw binding router: keyword → agent mapping
"""

import re
import logging

from services.agent.state import AgentContext, IntentType

logger = logging.getLogger(__name__)

# ── Rule-based intent matching (4 intents, zero latency) ──

INTENT_RULES: list[tuple[IntentType, re.Pattern, float]] = [
    # Layout actions (highest priority — direct UI control)
    (IntentType.LAYOUT, re.compile(
        r"(layout|resize|maximize|minimize|expand|collapse|"
        r"set_layout|change\s+layout|zoom\s+in|zoom\s+out|fullscreen|"
        r"switch\s+to\s+.*mode|hide\s+\w+|show\s+\w+|make\s+.*bigger|make\s+.*smaller|"
        # Block-level actions
        r"(add|remove|delete)\s+(the\s+|a\s+)?\w*\s*(block|card|widget)|"
        r"(add|remove|delete|show|hide)\s+(the\s+|a\s+)?(flashcard|note|forecast|knowledge.?graph|review|plan|progress|wrong.?answer|chapter)\s*(block|card|section|widget|s\b)?|"
        r"reorder|rearrange|reorganize|move\s+.*\s+(up|down|first|last)|"
        r"apply\s+(the\s+|a\s+)?.*template|use\s+(the\s+|a\s+)?.*template|"
        r"(exam.?prep|self.?paced|maintenance|course.?following)\s+mode)", re.IGNORECASE
    ), 0.95),

    # Study plan / scheduling
    (IntentType.PLAN, re.compile(
        r"(study\s+plan|review\s+schedule|plan\s+for|schedule|"
        r"how\s+should\s+I\s+study|help\s+me\s+plan|study\s+schedule|"
        r"schedule\s+for\s+finals|create\s+a\s+study\s+schedule|deadline)", re.IGNORECASE
    ), 0.90),

    # Learning — merged: teach, quiz, review, assess, curriculum, code, scene_switch
    (IntentType.LEARN, re.compile(
        r"(explain|what\s+is|how\s+does|why\s+does|define|concept|"
        r"tell\s+me\s+about|help\s+me\s+understand|teach\s+me|"
        r"don'?t\s+understand|clarify|"
        # quiz / exercise patterns
        r"quiz|exercise|test\s+me|practice|"
        r"generate\s+(quiz|question|questions|problem|practice\s+questions)|"
        r"give\s+me\s+(a\s+)?question|"
        # review / error analysis patterns
        r"wrong|mistake|error\s+analysis|review\s+my|"
        r"what\s+did\s+I\s+get\s+wrong|where\s+did\s+I\s+go\s+wrong|"
        r"why\s+(is|was)\s+(it|this)\s+wrong|"
        # curriculum patterns
        r"course\s+structure|knowledge\s+graph|outline|syllabus|curriculum|"
        r"prerequisite|topic\s+hierarchy|learning\s+path|"
        # assessment patterns
        r"assessment|my\s+progress|progress\s+report|"
        r"weak\s+area|how\s+am\s+I\s+doing|exam\s+readiness|mastery|"
        # code patterns
        r"run\s+(this|my|the)\s+code|debug|```python|code\s+execution|"
        # scene switch patterns
        r"prepare\s+for\s+(an?\s+)?exam|exam\s+prep|start\s+review|"
        r"do\s+(my\s+)?homework|error\s+drill|review\s+mistakes)", re.IGNORECASE
    ), 0.80),
]


def rule_match(message: str) -> tuple[IntentType, float] | None:
    """Fast regex-based intent detection.

    Returns (intent, confidence) if a rule matches, else None.
    """
    for intent, pattern, confidence in INTENT_RULES:
        if pattern.search(message):
            return intent, confidence
    return None


async def classify_intent(ctx: AgentContext) -> AgentContext:
    """Rule-based intent classification (Phase 2: no LLM fallback).

    Updates ctx.intent and ctx.intent_confidence in-place.
    Falls back to GENERAL if no rule matches.
    """
    message = ctx.user_message

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

    # No rule matched → GENERAL fallback
    ctx.intent = IntentType.GENERAL
    ctx.intent_confidence = 0.5
    logger.info(
        "Intent classified as GENERAL (no rule match) msg=%s",
        message[:60],
    )
    return ctx
