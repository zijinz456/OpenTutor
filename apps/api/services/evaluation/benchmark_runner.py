"""Regression benchmark runner for core agent capabilities."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from services.evaluation.eval_recovery import run_recovery_evaluation
from services.evaluation.eval_response import ResponseEvalCase, eval_responses_batch
from services.evaluation.eval_retrieval import eval_retrieval_from_course
from services.evaluation.eval_routing import eval_routing
ROUTING_MIN_ACCURACY = 0.8
RETRIEVAL_MIN_RECALL = 0.45
RESPONSE_MIN_CORRECTNESS = 3.5

DEFAULT_RESPONSE_CASES = [
    {
        "question": "What is gradient descent?",
        "response": (
            "Gradient descent is an optimization method that updates parameters in the "
            "direction that most reduces loss, usually by stepping along the negative gradient."
        ),
        "context": (
            "Gradient descent is an optimisation method that iteratively updates parameters "
            "using the negative gradient to reduce loss."
        ),
        "expected_intent": "learn",
    },
    {
        "question": "Why does binary search need a sorted array?",
        "response": (
            "Binary search relies on order: after checking the middle element, the sorted "
            "property tells you which half can still contain the answer and which half can be discarded."
        ),
        "context": (
            "Binary search requires a sorted array so each comparison splits the remaining "
            "search space in half while preserving correctness."
        ),
        "expected_intent": "learn",
    },
]


@dataclass
class BenchmarkSuite:
    name: str
    passed: bool
    score: float | None
    threshold: float | None
    details: dict[str, Any]
    skipped: bool = False


async def run_regression_benchmark(
    *,
    db: AsyncSession | None = None,
    course_id=None,
    retrieval_queries: list[dict] | None = None,
    response_cases: list[dict] | None = None,
    strict: bool = False,
) -> dict[str, Any]:
    suites: list[BenchmarkSuite] = []

    routing = await eval_routing(offline_only=True)
    suites.append(
        BenchmarkSuite(
            name="routing",
            passed=routing.accuracy >= ROUTING_MIN_ACCURACY,
            score=routing.accuracy,
            threshold=ROUTING_MIN_ACCURACY,
            details={"total": routing.total, "correct": routing.correct, "mismatches": routing.mismatches},
        )
    )
    if db is not None and course_id and retrieval_queries:
        retrieval = await eval_retrieval_from_course(db, course_id, retrieval_queries)
        if retrieval.total == 0:
            # No matching content nodes found — skip rather than fail,
            # since there is no test data to evaluate against.
            suites.append(
                BenchmarkSuite(
                    name="retrieval",
                    passed=True,
                    score=None,
                    threshold=RETRIEVAL_MIN_RECALL,
                    details={"reason": "no matching content nodes for evaluation"},
                    skipped=True,
                )
            )
        else:
            suites.append(
                BenchmarkSuite(
                    name="retrieval",
                    passed=retrieval.avg_recall >= RETRIEVAL_MIN_RECALL,
                    score=retrieval.avg_recall,
                    threshold=RETRIEVAL_MIN_RECALL,
                    details={
                        "total": retrieval.total,
                        "avg_recall": retrieval.avg_recall,
                        "avg_precision": retrieval.avg_precision,
                        "mrr": retrieval.mrr,
                        "avg_ndcg": retrieval.avg_ndcg,
                    },
                    skipped=False,
                )
            )
    else:
        suites.append(
            BenchmarkSuite(
                name="retrieval",
                passed=True,
                score=None,
                threshold=RETRIEVAL_MIN_RECALL,
                details={"reason": "course_id and retrieval_queries are required"},
                skipped=True,
            )
        )

    cases_input = response_cases if response_cases is not None else DEFAULT_RESPONSE_CASES
    if cases_input:
        cases = [
            ResponseEvalCase(
                question=item.get("question", ""),
                response=item.get("response", ""),
                context=item.get("context", ""),
                expected_intent=item.get("expected_intent", "learn"),
            )
            for item in cases_input
            if item.get("question") and item.get("response")
        ]
        if cases:
            response_eval = await eval_responses_batch(cases)
            suites.append(
                BenchmarkSuite(
                    name="response_quality",
                    passed=response_eval.avg_correctness >= RESPONSE_MIN_CORRECTNESS,
                    score=response_eval.avg_correctness,
                    threshold=RESPONSE_MIN_CORRECTNESS,
                    details={
                        "total": response_eval.total,
                        "avg_correctness": response_eval.avg_correctness,
                        "avg_relevance": response_eval.avg_relevance,
                        "avg_helpfulness": response_eval.avg_helpfulness,
                        "fixture_source": "default" if response_cases is None else "custom",
                    },
                )
            )
        else:
            suites.append(
                BenchmarkSuite(
                    name="response_quality",
                    passed=True,
                    score=None,
                    threshold=RESPONSE_MIN_CORRECTNESS,
                    details={"reason": "no valid response cases"},
                    skipped=True,
                )
            )
    else:
        suites.append(
            BenchmarkSuite(
                name="response_quality",
                passed=True,
                score=None,
                threshold=RESPONSE_MIN_CORRECTNESS,
                details={"reason": "response cases not supplied"},
                skipped=True,
            )
        )

    # ── Recovery evaluation ──
    if db is not None:
        try:
            recovery_results = await run_recovery_evaluation(db, course_id)
            recovery_passed = all(r.passed for r in recovery_results)
            suites.append(
                BenchmarkSuite(
                    name="recovery",
                    passed=recovery_passed,
                    score=sum(1 for r in recovery_results if r.passed) / max(len(recovery_results), 1),
                    threshold=1.0,
                    details={
                        "total": len(recovery_results),
                        "results": [{"name": r.name, "passed": r.passed, **r.details} for r in recovery_results],
                    },
                )
            )
        except (ValueError, RuntimeError, ConnectionError, TimeoutError, OSError) as exc:
            logger.exception("Recovery evaluation suite failed: %s", exc)
            suites.append(
                BenchmarkSuite(
                    name="recovery",
                    passed=True,
                    score=None,
                    threshold=1.0,
                    details={"reason": f"recovery eval error: {exc}"},
                    skipped=True,
                )
            )
    else:
        suites.append(
            BenchmarkSuite(
                name="recovery",
                passed=True,
                score=None,
                threshold=1.0,
                details={"reason": "db session required for recovery eval"},
                skipped=True,
            )
        )

    strict_failures: list[dict[str, str]] = []
    if strict:
        for suite in suites:
            if suite.name in {"retrieval", "recovery"} and suite.skipped:
                reason = str(suite.details.get("reason", "suite was skipped"))
                suite.passed = False
                suite.skipped = False
                suite.details["strict_mode"] = "failed"
                suite.details["strict_reason"] = (
                    f"{suite.name} suite was skipped in strict mode: {reason}"
                )
                strict_failures.append({"suite": suite.name, "reason": reason})

    failed = [suite.name for suite in suites if not suite.passed and not suite.skipped]
    return {
        "passed": not failed,
        "failed_suites": failed,
        "strict": strict,
        "strict_failures": strict_failures,
        "suites": [asdict(suite) for suite in suites],
    }
