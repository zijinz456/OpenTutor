"""Evaluation: Intent routing accuracy.

Compares predicted intents against golden labels from test transcripts.
Used for offline eval to ensure agent routing quality doesn't regress.
"""

import logging
from dataclasses import dataclass

from services.agent.state import AgentContext, IntentType
from services.agent.router import classify_intent, rule_match

logger = logging.getLogger(__name__)


@dataclass
class RoutingEvalCase:
    """A single routing evaluation case."""
    message: str
    expected_intent: str
    context: dict | None = None


@dataclass
class RoutingEvalResult:
    """Result of evaluating routing accuracy."""
    total: int
    correct: int
    accuracy: float
    mismatches: list[dict]


# Golden test cases for intent routing
GOLDEN_ROUTING_CASES = [
    RoutingEvalCase("What is calculus?", "learn"),
    RoutingEvalCase("Give me some practice problems", "learn"),
    RoutingEvalCase("Create a study plan for me", "plan"),
    RoutingEvalCase("What did I get wrong last time?", "learn"),
    RoutingEvalCase("Change the note format to a list", "general"),
    RoutingEvalCase("What is the derivative of x^2?", "learn"),
    RoutingEvalCase("Generate 5 practice questions on Chapter 3", "learn"),
    RoutingEvalCase("Create a study schedule for finals", "plan"),
    RoutingEvalCase("Review my wrong answers from last week", "learn"),
    RoutingEvalCase("Switch to exam mode", "layout"),
    RoutingEvalCase("Run this Python code", "general"),
    RoutingEvalCase("Analyze the structure of this course", "general"),
    RoutingEvalCase("Evaluate my learning progress", "general"),
    RoutingEvalCase("Hello", "general"),
    RoutingEvalCase("Thanks for helping me!", "general"),
]


async def eval_routing(
    cases: list[RoutingEvalCase] | None = None,
    user_id=None,
    course_id=None,
    offline_only: bool = False,
) -> RoutingEvalResult:
    """Run routing evaluation against golden cases.

    Returns accuracy metrics and list of mismatched predictions.
    """
    import uuid
    cases = cases or GOLDEN_ROUTING_CASES
    uid = user_id or uuid.uuid4()
    cid = course_id or uuid.uuid4()

    correct = 0
    mismatches = []

    for case in cases:
        ctx = AgentContext(
            user_id=uid,
            course_id=cid,
            user_message=case.message,
        )
        if offline_only:
            matched = rule_match(case.message)
            if matched:
                ctx.intent, ctx.intent_confidence = matched
            else:
                ctx.intent = IntentType.GENERAL
                ctx.intent_confidence = 0.3
        else:
            ctx = await classify_intent(ctx)
        predicted = ctx.intent.value

        if predicted == case.expected_intent:
            correct += 1
        else:
            mismatches.append({
                "message": case.message,
                "expected": case.expected_intent,
                "predicted": predicted,
                "confidence": ctx.intent_confidence,
            })

    total = len(cases)
    return RoutingEvalResult(
        total=total,
        correct=correct,
        accuracy=correct / total if total > 0 else 0.0,
        mismatches=mismatches,
    )
