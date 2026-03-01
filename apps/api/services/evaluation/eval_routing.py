"""Evaluation: Intent routing accuracy.

Compares predicted intents against golden labels from test transcripts.
Used for offline eval to ensure agent routing quality doesn't regress.
"""

import logging
from dataclasses import dataclass

from services.agent.state import AgentContext, IntentType
from services.agent.router import classify_intent

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
    RoutingEvalCase("什么是微积分？", "learn"),
    RoutingEvalCase("帮我出几道练习题", "quiz"),
    RoutingEvalCase("制定一个学习计划", "plan"),
    RoutingEvalCase("我上次错了什么？", "review"),
    RoutingEvalCase("把笔记格式改成列表", "preference"),
    RoutingEvalCase("What is the derivative of x^2?", "learn"),
    RoutingEvalCase("Generate 5 practice questions on Chapter 3", "quiz"),
    RoutingEvalCase("Create a study schedule for finals", "plan"),
    RoutingEvalCase("Review my wrong answers from last week", "review"),
    RoutingEvalCase("切换到考试模式", "scene_switch"),
    RoutingEvalCase("运行这段Python代码", "code"),
    RoutingEvalCase("分析一下这门课的结构", "curriculum"),
    RoutingEvalCase("评估一下我的学习进度", "assess"),
    RoutingEvalCase("Hello", "general"),
    RoutingEvalCase("Thanks for helping me!", "general"),
]


async def eval_routing(
    cases: list[RoutingEvalCase] | None = None,
    user_id=None,
    course_id=None,
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
