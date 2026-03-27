"""Evaluation: Response quality scoring via LLM-as-judge.

Uses a separate LLM call to evaluate agent responses on:
- Correctness: factual accuracy relative to course content
- Relevance: how well the response addresses the user's question
- Helpfulness: actionable, clear, appropriate for the student's level

Reference: "Judging LLM-as-a-Judge" (Zheng et al., 2023)
"""

import logging
from dataclasses import dataclass
import re

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-]{1,}")
_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")

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


def _tokenize(text: str) -> set[str]:
    tokens: set[str] = set()
    lowered = text.lower()
    for word in _WORD_RE.findall(lowered):
        tokens.add(word)
    for segment in _CJK_RE.findall(text):
        if len(segment) >= 2:
            tokens.add(segment)
            for size in (2, 3):
                if len(segment) >= size:
                    for idx in range(len(segment) - size + 1):
                        tokens.add(segment[idx : idx + size])
    return {token for token in tokens if len(token) >= 2}


def _scaled_score(ratio: float) -> float:
    if ratio >= 0.55:
        return 5.0
    if ratio >= 0.35:
        return 4.0
    if ratio >= 0.18:
        return 3.0
    if ratio >= 0.08:
        return 2.0
    return 1.0


def _heuristic_eval_response(question: str, response: str, context: str = "") -> ResponseScore:
    response_tokens = _tokenize(response)
    question_tokens = _tokenize(question)
    context_tokens = _tokenize(context)
    q_overlap = len(response_tokens & question_tokens) / max(len(question_tokens), 1)
    c_overlap = len(response_tokens & context_tokens) / max(len(context_tokens), 1) if context_tokens else q_overlap
    length_bonus = min(len(response.strip()) / 240, 1.0)
    structure_bonus = 0.25 if any(marker in response for marker in ("\n-", "\n1.", "1.", "2.", ":")) else 0.0

    correctness = min(5.0, max(1.0, _scaled_score(c_overlap) + (0.5 if context_tokens and c_overlap >= 0.2 else 0.0)))
    relevance = min(5.0, max(1.0, _scaled_score(q_overlap)))
    helpfulness = min(
        5.0,
        max(1.0, round((_scaled_score((q_overlap + c_overlap) / 2) + length_bonus + structure_bonus) * 2) / 2),
    )
    return ResponseScore(
        correctness=correctness,
        relevance=relevance,
        helpfulness=helpfulness,
        rationale={
            "mode": "heuristic",
            "question_overlap": round(q_overlap, 3),
            "context_overlap": round(c_overlap, 3),
            "length_bonus": round(length_bonus, 3),
        },
    )


async def eval_response(
    question: str,
    response: str,
    context: str = "",
) -> ResponseScore:
    """Evaluate a single response using LLM-as-judge."""
    from services.llm.router import get_llm_client

    try:
        client = get_llm_client("small")  # Use cheaper model for judging
        if getattr(client, "provider_name", "") == "mock":
            return _heuristic_eval_response(question, response, context)
        from libs.text_utils import parse_llm_json

        prompt = _JUDGE_PROMPT.format(
            question=question,
            context=context[:2000] if context else "(no context provided)",
            response=response[:3000],
        )
        result, _ = await client.chat(
            "You are an evaluation judge. Output valid JSON only.",
            prompt,
        )
        scores = parse_llm_json(result, default=None)
        if not isinstance(scores, dict):
            raise ValueError("Judge did not return a JSON object")
        return ResponseScore(
            correctness=scores.get("correctness", {}).get("score", 3),
            relevance=scores.get("relevance", {}).get("score", 3),
            helpfulness=scores.get("helpfulness", {}).get("score", 3),
            rationale=scores,
        )
    except (ConnectionError, TimeoutError, ValueError, KeyError, RuntimeError, Exception) as exc:
        logger.exception("Response evaluation LLM call failed: %s", exc)
        return _heuristic_eval_response(question, response, context)


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
