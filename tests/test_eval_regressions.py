import pytest

from services.evaluation.benchmark_runner import run_regression_benchmark, run_scene_policy_benchmark
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
