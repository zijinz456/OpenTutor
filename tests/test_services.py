"""Unit tests for service layer — no database or HTTP required."""

import math
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
        "exam_review": "期末复习",
        "assignment": "homework problem",
        "weekly_prep": "这周要学什么",
    }
    for scene, text in examples.items():
        if scene in [p[1] for p in SCENE_PATTERNS]:
            assert detect_scene(text) == scene, f"Failed for scene={scene}, text={text}"


def test_detect_scene_default_for_random_text():
    assert detect_scene("hello how are you doing") == DEFAULT_SCENE
    assert detect_scene("") == DEFAULT_SCENE


# ── Ingestion: filename classification ──

from services.ingestion.pipeline import classify_by_filename, detect_mime_type


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
