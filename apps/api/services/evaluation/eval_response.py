"""Evaluation: Response quality scoring via LLM-as-judge.

Uses a separate LLM call to evaluate agent responses on:
- Correctness: factual accuracy relative to course content
- Relevance: how well the response addresses the user's question
- Helpfulness: actionable, clear, appropriate for the student's level

Reference: "Judging LLM-as-a-Judge" (Zheng et al., 2023)
"""

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """You are an expert education evaluator. Rate the following tutor response on three dimensions.

**Student question**: {question}
**Course context** (ground truth): {context}
**Tutor response**: {response}

Rate each dimension 1-5:
1. **Correctness** (1=wrong, 5=perfectly accurate given the course materials)
2. **Relevance** (1=off-topic, 5=directly addresses the question)
3. **Helpfulness** (1=confusing, 5=clear, actionable, well-structured)

Also provide a brief rationale for each score.

Return ONLY JSON:
{{"correctness": {{"score": N, "rationale": "..."}}, "relevance": {{"score": N, "rationale": "..."}}, "helpfulness": {{"score": N, "rationale": "..."}}}}"""


@dataclass
class ResponseEvalCase:
    """A single response evaluation case."""
    question: str
    response: str
    context: str = ""  # ground truth from course content
    expected_intent: str = "learn"


@dataclass
class ResponseScore:
    """Scores for a single response."""
    correctness: float
    relevance: float
    helpfulness: float
    rationale: dict


@dataclass
class ResponseEvalResult:
    """Aggregate response evaluation results."""
    total: int
    avg_correctness: float
    avg_relevance: float
    avg_helpfulness: float
    scores: list[ResponseScore]


async def eval_response(
    question: str,
    response: str,
    context: str = "",
) -> ResponseScore:
    """Evaluate a single response using LLM-as-judge."""
    from services.llm.router import get_llm_client

    client = get_llm_client("small")  # Use cheaper model for judging
    prompt = _JUDGE_PROMPT.format(
        question=question,
        context=context[:2000] if context else "(no context provided)",
        response=response[:3000],
    )

    try:
        result, _ = await client.chat(
            "You are an evaluation judge. Output valid JSON only.",
            prompt,
        )
        scores = json.loads(result)
        return ResponseScore(
            correctness=scores.get("correctness", {}).get("score", 3),
            relevance=scores.get("relevance", {}).get("score", 3),
            helpfulness=scores.get("helpfulness", {}).get("score", 3),
            rationale=scores,
        )
    except Exception as e:
        logger.error("Response evaluation failed: %s", e)
        return ResponseScore(
            correctness=0, relevance=0, helpfulness=0,
            rationale={"error": str(e)},
        )


async def eval_responses_batch(
    cases: list[ResponseEvalCase],
) -> ResponseEvalResult:
    """Evaluate a batch of responses."""
    scores = []
    for case in cases:
        score = await eval_response(case.question, case.response, case.context)
        scores.append(score)

    total = len(scores)
    valid = [s for s in scores if s.correctness > 0]

    return ResponseEvalResult(
        total=total,
        avg_correctness=sum(s.correctness for s in valid) / len(valid) if valid else 0,
        avg_relevance=sum(s.relevance for s in valid) / len(valid) if valid else 0,
        avg_helpfulness=sum(s.helpfulness for s in valid) / len(valid) if valid else 0,
        scores=scores,
    )
