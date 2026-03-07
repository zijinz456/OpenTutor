import pytest

from services.evaluation.benchmark_runner import run_regression_benchmark
from services.evaluation.eval_retrieval import _CourseNodeSnapshot, _build_relevant_ids_from_keywords


@pytest.mark.asyncio
async def test_regression_benchmark_runs_offline_suites_without_optional_inputs():
    result = await run_regression_benchmark()

    assert result["passed"] is True
    suite_names = {suite["name"] for suite in result["suites"]}
    assert {"routing", "retrieval", "response_quality", "recovery"} <= suite_names
    retrieval_suite = next(s for s in result["suites"] if s["name"] == "retrieval")
    assert retrieval_suite["skipped"] is True
    response_suite = next(s for s in result["suites"] if s["name"] == "response_quality")
    assert response_suite["skipped"] is False
    assert response_suite["details"]["fixture_source"] == "default"


@pytest.mark.asyncio
async def test_regression_benchmark_strict_mode_fails_when_retrieval_or_recovery_is_skipped():
    result = await run_regression_benchmark(strict=True)

    assert result["strict"] is True
    assert result["passed"] is False
    assert {"retrieval", "recovery"} <= set(result["failed_suites"])
    strict_failures = {entry["suite"] for entry in result["strict_failures"]}
    assert {"retrieval", "recovery"} <= strict_failures


def test_retrieval_ground_truth_prefers_searchable_content_nodes():
    nodes = [
        _CourseNodeSnapshot(id="root", title="sample-course.md", content=None, parent_id=None),
        _CourseNodeSnapshot(id="chapter", title="Binary Search Basics", content=None, parent_id="root"),
        _CourseNodeSnapshot(
            id="core",
            title="Core Idea",
            content="Binary search works on sorted data and halves the search interval.",
            parent_id="chapter",
        ),
        _CourseNodeSnapshot(
            id="pitfalls",
            title="Common Pitfalls",
            content="Off-by-one errors are a common pitfall in binary search.",
            parent_id="chapter",
        ),
    ]

    query1_ids = _build_relevant_ids_from_keywords(nodes, ["binary search", "pitfalls", "off-by-one"])
    query2_ids = _build_relevant_ids_from_keywords(nodes, ["binary search", "sorted", "search interval"])

    assert query1_ids == ["pitfalls"]
    assert query2_ids == ["core"]
