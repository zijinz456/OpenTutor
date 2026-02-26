import asyncio

import pytest
from fastapi import HTTPException

from routers.preferences import _normalize_preference_value
from routers.workflows import _raise_if_service_error
from services.llm import router as llm_router
from services.preference.scene import DEFAULT_SCENE, detect_scene


def test_normalize_preference_value_basic_mappings():
    assert _normalize_preference_value("detail_level", "moderate") == "balanced"
    assert _normalize_preference_value("language", "zh-cn") == "zh"
    assert _normalize_preference_value("explanation_style", "analogy") == "example_heavy"
    assert _normalize_preference_value("note_format", "table") == "table"


def test_detect_scene_supports_cn_and_en_keywords():
    assert detect_scene("请帮我复习期末考试重点") == "exam_review"
    assert detect_scene("homework problem set for chapter 3") == "assignment"
    assert detect_scene("just chatting without task") == DEFAULT_SCENE


def test_workflow_service_error_mapping():
    _raise_if_service_error({})

    with pytest.raises(HTTPException) as not_found:
        _raise_if_service_error({"error": "Assignment not found"})
    assert not_found.value.status_code == 404

    with pytest.raises(HTTPException) as bad_request:
        _raise_if_service_error({"error": "Invalid input"})
    assert bad_request.value.status_code == 400


def test_llm_router_falls_back_to_mock_without_keys(monkeypatch):
    monkeypatch.setattr(llm_router.settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "deepseek_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "llm_provider", "openai", raising=False)
    monkeypatch.setattr(llm_router, "_registry", None, raising=False)

    client = llm_router.get_llm_client()
    response = asyncio.run(client.chat("system", "hello"))
    assert "No LLM API key configured" in response
