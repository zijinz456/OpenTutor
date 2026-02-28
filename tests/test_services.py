"""Unit tests for service layer — no database or HTTP required."""

import math
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# ── Search: RRF scoring ──

from services.search.hybrid import rrf_score, RRF_K


def test_rrf_score_formula():
    assert rrf_score(1) == pytest.approx(1 / (RRF_K + 1))
    assert rrf_score(10) == pytest.approx(1 / (RRF_K + 10))
    assert rrf_score(1) > rrf_score(2) > rrf_score(10)


def test_rrf_score_monotonically_decreasing():
    scores = [rrf_score(r) for r in range(1, 20)]
    for i in range(len(scores) - 1):
        assert scores[i] > scores[i + 1]


# ── Preference: confidence calculation ──

from services.preference.confidence import recency_factor, BASE_SCORES


def test_recency_factor_recent_is_high():
    now = datetime.now(timezone.utc)
    assert recency_factor(now) == pytest.approx(1.0, abs=0.01)


def test_recency_factor_90_days_decayed():
    old = datetime.now(timezone.utc) - timedelta(days=90)
    factor = recency_factor(old)
    # exp(-90/90) ≈ 0.368
    assert 0.3 < factor < 0.4


def test_base_scores_explicit_highest():
    assert BASE_SCORES["explicit"] > BASE_SCORES["modification"]
    assert BASE_SCORES["modification"] > BASE_SCORES["behavior"]


def test_base_scores_all_types_defined():
    for signal_type in ("explicit", "modification", "behavior", "negative"):
        assert signal_type in BASE_SCORES
        assert BASE_SCORES[signal_type] > 0


# ── Scene detection: all patterns ──

from services.preference.scene import detect_scene, DEFAULT_SCENE, SCENE_PATTERNS


def test_detect_scene_all_defined_patterns():
    """Each scene regex should match at least one example."""
    examples = {
        "exam_prep": "期末复习",
        "review_drill": "错题复盘",
        "assignment": "homework problem",
        "note_organize": "帮我整理笔记",
        "study_session": "please explain this concept",
    }
    supported_scenes = {scene_name for scene_name, _ in SCENE_PATTERNS}
    for scene, text in examples.items():
        assert scene in supported_scenes, f"Example uses unknown scene={scene}"
        assert detect_scene(text) == scene, f"Failed for scene={scene}, text={text}"


def test_detect_scene_default_for_random_text():
    assert detect_scene("hello how are you doing") == DEFAULT_SCENE
    assert detect_scene("") == DEFAULT_SCENE


# ── Ingestion: filename classification ──

from services.ingestion.pipeline import classify_by_filename, detect_mime_type
from services.parser.quiz import _normalize_problem_metadata
from services.practice.annotation import normalize_problem_annotation, parse_question_array


def test_classify_by_filename_lecture():
    assert classify_by_filename("Lecture_03.pdf") == "lecture_slides"
    assert classify_by_filename("CS101_slides.pptx") == "lecture_slides"


def test_classify_by_filename_assignment():
    assert classify_by_filename("hw3_solutions.pdf") == "assignment"
    assert classify_by_filename("problem_set_2.pdf") == "assignment"


def test_classify_by_filename_exam():
    assert classify_by_filename("final_exam_2024.pdf") == "exam_schedule"
    assert classify_by_filename("midterm_review.pdf") == "exam_schedule"


def test_classify_by_filename_no_match():
    assert classify_by_filename("random_file.pdf") is None


def test_detect_mime_type_by_extension():
    assert "pdf" in detect_mime_type("test.pdf")
    # .xyz has a registered MIME; use truly unknown extension
    assert detect_mime_type("unknown.zzzzz") == "application/octet-stream"


def test_normalize_problem_metadata_applies_generic_defaults():
    layer, metadata = _normalize_problem_metadata(
        {
            "question_type": "fill_blank",
            "question": "The ____ is the powerhouse of the cell.",
        },
        title="Cell Biology",
    )

    assert layer == 1
    assert metadata["core_concept"] == "Cell Biology"
    assert metadata["bloom_level"] == "remember"
    assert metadata["skill_focus"] == "recall"
    assert metadata["source_section"] == "Cell Biology"


def test_shared_problem_annotation_pipeline_adds_common_contract():
    normalized = normalize_problem_annotation(
        {
            "question_type": "short_answer",
            "question": "Explain osmosis.",
            "problem_metadata": {"core_concept": "osmosis"},
        },
        title="Membrane Transport",
        source="generated",
    )

    assert normalized["difficulty_layer"] == 2
    assert normalized["problem_metadata"]["core_concept"] == "osmosis"
    assert normalized["problem_metadata"]["source_kind"] == "generated"
    assert normalized["problem_metadata"]["skill_focus"] == "explanation"


def test_parse_question_array_handles_markdown_wrapped_json():
    parsed = parse_question_array(
        """```json
        [{"question_type":"mc","question":"Q?","options":{"A":"x","B":"y","C":"z","D":"w"}}]
        ```"""
    )

    assert len(parsed) == 1
    assert parsed[0]["question"] == "Q?"


# ── Embedding: registry pattern ──

def test_embedding_registry_raises_without_providers():
    """Without OpenAI key or sentence-transformers, registry should raise."""
    from services.embedding import registry
    from config import settings as real_settings

    original_key = real_settings.openai_api_key
    try:
        real_settings.openai_api_key = ""
        registry._provider = None
        with patch.dict("sys.modules", {"services.embedding.local": None}):
            with pytest.raises((RuntimeError, ImportError)):
                registry.get_embedding_provider()
    finally:
        real_settings.openai_api_key = original_key
        registry._provider = None


# ── Auth: password hashing ──

from services.auth.password import hash_password, verify_password


def test_password_hash_and_verify():
    password = "test_password_123"
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrong_password", hashed)


# ── Auth: JWT tokens ──

from services.auth.jwt import create_access_token, create_refresh_token, decode_token


def test_jwt_access_token_roundtrip():
    user_id = "test-user-id-123"
    token = create_access_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == user_id
    assert payload["type"] == "access"


def test_jwt_refresh_token_roundtrip():
    user_id = "test-user-id-456"
    token = create_refresh_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == user_id
    assert payload["type"] == "refresh"


# ── Scene switching ──

from services.scene import manager as scene_manager


@pytest.mark.asyncio
async def test_switch_scene_uses_snapshot_open_tabs_for_tab_layout(monkeypatch):
    course_id = uuid.uuid4()
    user_id = uuid.uuid4()
    fake_course = MagicMock(active_scene="study_session")
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = fake_course
    db = MagicMock()
    db.execute = AsyncMock(return_value=fake_result)
    db.flush = AsyncMock()
    db.add = MagicMock()

    async def fake_get_scene_config(_db, _scene_id):
        return {
            "scene_id": "exam_prep",
            "tab_preset": [{"type": "plan", "position": 0}],
        }

    async def fake_load_snapshot(_db, _course_id, _scene_id):
        return {
            "open_tabs": [{"type": "review", "position": 0}],
            "layout_state": {"panel_sizes": [50, 50]},
        }

    async def fake_get_init_actions(_db, _course_id, _user_id, _scene_id):
        return []

    monkeypatch.setattr(scene_manager, "get_scene_config", fake_get_scene_config)
    monkeypatch.setattr(scene_manager, "load_snapshot", fake_load_snapshot)
    monkeypatch.setattr(scene_manager, "get_init_actions", fake_get_init_actions)

    result = await scene_manager.switch_scene(
        db=db,
        course_id=course_id,
        user_id=user_id,
        new_scene_id="exam_prep",
    )

    assert result["tab_layout"] == [{"type": "review", "position": 0}]


def test_resolve_tab_layout_falls_back_to_scene_defaults():
    scene_config = {"tab_preset": [{"type": "notes", "position": 0}]}

    assert scene_manager._resolve_tab_layout(scene_config, None) == scene_config["tab_preset"]
    assert scene_manager._resolve_tab_layout(scene_config, {"open_tabs": []}) == scene_config["tab_preset"]
