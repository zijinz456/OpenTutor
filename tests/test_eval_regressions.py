import pytest

from services.evaluation.benchmark_runner import run_regression_benchmark, run_scene_policy_benchmark
from services.evaluation.eval_retrieval import _CourseNodeSnapshot, _build_relevant_ids_from_keywords
from services.scene.policy import decide_scene_policy_from_features


def test_scene_policy_prefers_review_drill_for_mistake_heavy_context():
    decision = decide_scene_policy_from_features(
        current_scene="study_session",
        features={
            "matched_cues": {
                "exam_prep": [],
                "assignment": [],
                "review_drill": ["wrong answer"],
                "note_organize": [],
                "study_session": [],
            },
            "upcoming_assignments": 0,
            "unmastered_wrong_answers": 5,
            "low_mastery_count": 3,
            "content_nodes": 10,
            "active_tab": "review",
            "course_active_scene": "study_session",
        },
    )

    assert decision.scene_id == "review_drill"
    assert decision.switch_recommended is True


def test_scene_policy_benchmark_passes_default_thresholds():
    result = run_scene_policy_benchmark()

    assert result.passed is True
    assert result.score is not None
    assert result.score >= result.threshold


@pytest.mark.asyncio
async def test_regression_benchmark_runs_offline_suites_without_optional_inputs():
    result = await run_regression_benchmark()

    assert result["passed"] is True
    suite_names = {suite["name"] for suite in result["suites"]}
    assert {"routing", "scene_policy", "retrieval", "response_quality"} <= suite_names
    retrieval_suite = next(s for s in result["suites"] if s["name"] == "retrieval")
    assert retrieval_suite["skipped"] is True
    response_suite = next(s for s in result["suites"] if s["name"] == "response_quality")
    assert response_suite["skipped"] is False
    assert response_suite["details"]["fixture_source"] == "default"


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
