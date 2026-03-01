"""Regression benchmark runner for core agent capabilities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from services.evaluation.eval_response import ResponseEvalCase, eval_responses_batch
from services.evaluation.eval_retrieval import eval_retrieval_from_course
from services.evaluation.eval_routing import eval_routing
from services.scene.policy import decide_scene_policy_from_features

ROUTING_MIN_ACCURACY = 0.8
SCENE_POLICY_MIN_ACCURACY = 0.8
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


SCENE_POLICY_CASES = [
    {
        "name": "exam prep weak areas",
        "expected_scene": "exam_prep",
        "current_scene": "study_session",
        "features": {
            "matched_cues": {"exam_prep": ["final"], "assignment": [], "review_drill": [], "note_organize": [], "study_session": []},
            "upcoming_assignments": 1,
            "unmastered_wrong_answers": 2,
            "low_mastery_count": 4,
            "content_nodes": 12,
            "active_tab": "plan",
            "course_active_scene": "study_session",
        },
    },
    {
        "name": "homework focus",
        "expected_scene": "assignment",
        "current_scene": "study_session",
        "features": {
            "matched_cues": {"exam_prep": [], "assignment": ["assignment"], "review_drill": [], "note_organize": [], "study_session": []},
            "upcoming_assignments": 3,
            "unmastered_wrong_answers": 0,
            "low_mastery_count": 1,
            "content_nodes": 7,
            "active_tab": "",
            "course_active_scene": "study_session",
        },
    },
    {
        "name": "mistake drill",
        "expected_scene": "review_drill",
        "current_scene": "study_session",
        "features": {
            "matched_cues": {"exam_prep": [], "assignment": [], "review_drill": ["wrong answer"], "note_organize": [], "study_session": []},
            "upcoming_assignments": 0,
            "unmastered_wrong_answers": 6,
            "low_mastery_count": 2,
            "content_nodes": 9,
            "active_tab": "review",
            "course_active_scene": "study_session",
        },
    },
    {
        "name": "notes synthesis",
        "expected_scene": "note_organize",
        "current_scene": "study_session",
        "features": {
            "matched_cues": {"exam_prep": [], "assignment": [], "review_drill": [], "note_organize": ["organize notes"], "study_session": []},
            "upcoming_assignments": 0,
            "unmastered_wrong_answers": 0,
            "low_mastery_count": 0,
            "content_nodes": 18,
            "active_tab": "notes",
            "course_active_scene": "study_session",
        },
    },
    {
        "name": "plain explanation request",
        "expected_scene": "study_session",
        "current_scene": "study_session",
        "features": {
            "matched_cues": {"exam_prep": [], "assignment": [], "review_drill": [], "note_organize": [], "study_session": ["explain"]},
            "upcoming_assignments": 0,
            "unmastered_wrong_answers": 0,
            "low_mastery_count": 0,
            "content_nodes": 6,
            "active_tab": "",
            "course_active_scene": "study_session",
        },
    },
]


def run_scene_policy_benchmark() -> BenchmarkSuite:
    mismatches: list[dict[str, Any]] = []
    correct = 0

    for case in SCENE_POLICY_CASES:
        decision = decide_scene_policy_from_features(
            features=case["features"],
            current_scene=case["current_scene"],
        )
        if decision.scene_id == case["expected_scene"]:
            correct += 1
        else:
            mismatches.append(
                {
                    "case": case["name"],
                    "expected": case["expected_scene"],
                    "predicted": decision.scene_id,
                    "reason": decision.reason,
                    "scores": decision.scores,
                }
            )

    accuracy = correct / len(SCENE_POLICY_CASES)
    return BenchmarkSuite(
        name="scene_policy",
        passed=accuracy >= SCENE_POLICY_MIN_ACCURACY,
        score=accuracy,
        threshold=SCENE_POLICY_MIN_ACCURACY,
        details={"total": len(SCENE_POLICY_CASES), "correct": correct, "mismatches": mismatches},
    )


async def run_regression_benchmark(
    *,
    db: AsyncSession | None = None,
    course_id=None,
    retrieval_queries: list[dict] | None = None,
    response_cases: list[dict] | None = None,
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
    suites.append(run_scene_policy_benchmark())

    if db is not None and course_id and retrieval_queries:
        retrieval = await eval_retrieval_from_course(db, course_id, retrieval_queries)
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

    failed = [suite.name for suite in suites if not suite.passed and not suite.skipped]
    return {
        "passed": not failed,
        "failed_suites": failed,
        "suites": [asdict(suite) for suite in suites],
    }
