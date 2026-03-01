import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

import pytest
from fastapi import HTTPException

from libs.exceptions import NotFoundError, ValidationError
from routers.chat import _build_session_title, _resolve_chat_session
from routers.goals import get_next_action
from routers.preferences import _normalize_preference_value
from routers.upload import _validate_url
from routers.wrong_answers import derive_question, diagnose_from_pair
from routers.workflows import _raise_if_service_error
from services.auth.dependency import get_current_user
from services.llm.local_config import get_llm_runtime_config, update_llm_runtime_config
from services.llm import router as llm_router
from services.preference.scene import DEFAULT_SCENE, detect_scene


def test_normalize_preference_value_basic_mappings():
    assert _normalize_preference_value("detail_level", "moderate") == "balanced"
    assert _normalize_preference_value("language", "zh-cn") == "zh"
    assert _normalize_preference_value("explanation_style", "analogy") == "example_heavy"
    assert _normalize_preference_value("note_format", "table") == "table"


def test_detect_scene_supports_en_keywords():
    assert detect_scene("help me review for the final exam") == "exam_prep"
    assert detect_scene("homework problem set for chapter 3") == "assignment"
    assert detect_scene("just chatting without task") == DEFAULT_SCENE


def test_workflow_service_error_mapping():
    _raise_if_service_error({})

    with pytest.raises(NotFoundError) as not_found:
        _raise_if_service_error({"error": "Assignment not found"})
    assert not_found.value.status == 404

    with pytest.raises(ValidationError) as bad_request:
        _raise_if_service_error({"error": "Invalid input"})
    assert bad_request.value.status == 422


def test_llm_router_falls_back_to_mock_without_keys(monkeypatch):
    monkeypatch.setattr(llm_router.settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "deepseek_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "llm_provider", "openai", raising=False)
    monkeypatch.setattr(llm_router, "_registry", None, raising=False)

    client = llm_router.get_llm_client()
    response, usage = asyncio.run(client.chat("system", "hello"))
    assert "No LLM API key configured" in response
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0


def test_llm_router_raises_when_llm_required_without_provider(monkeypatch):
    monkeypatch.setattr(llm_router.settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "deepseek_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "gemini_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "groq_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "llm_required", True, raising=False)
    monkeypatch.setattr(llm_router, "_registry", None, raising=False)

    with pytest.raises(llm_router.LLMConfigurationError):
        llm_router.get_llm_client()

    monkeypatch.setattr(llm_router.settings, "llm_required", False, raising=False)


def test_update_llm_runtime_config_persists_and_masks(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    monkeypatch.setattr("services.llm.local_config._env_path", lambda: env_path)
    monkeypatch.setattr(llm_router, "_registry", "sentinel", raising=False)

    config = update_llm_runtime_config(
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "llm_required": True,
            "provider_keys": {"openai": "sk-test-12345678"},
        }
    )

    assert config["provider"] == "openai"
    assert config["llm_required"] is True
    openai_status = next(item for item in config["providers"] if item["provider"] == "openai")
    assert openai_status["has_key"] is True
    assert openai_status["masked_key"] == "sk-t...5678"
    assert "OPENAI_API_KEY=sk-test-12345678" in env_path.read_text()
    assert llm_router._registry is None


def test_get_llm_runtime_config_reads_existing_env(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=anthropic-secret-1234\n", encoding="utf-8")
    monkeypatch.setattr("services.llm.local_config._env_path", lambda: env_path)

    config = get_llm_runtime_config()

    anthropic_status = next(item for item in config["providers"] if item["provider"] == "anthropic")
    assert anthropic_status["has_key"] is True
    assert anthropic_status["masked_key"] == "anth...1234"


def test_update_llm_runtime_config_can_delete_saved_key(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-delete-me-9876\n", encoding="utf-8")
    monkeypatch.setattr("services.llm.local_config._env_path", lambda: env_path)
    monkeypatch.setattr(llm_router.settings, "openai_api_key", "sk-delete-me-9876", raising=False)

    config = update_llm_runtime_config({"provider_keys": {"openai": ""}})

    openai_status = next(item for item in config["providers"] if item["provider"] == "openai")
    assert openai_status["has_key"] is False
    assert "OPENAI_API_KEY" not in env_path.read_text()


def test_build_session_title_trims_and_compacts_whitespace():
    title = _build_session_title("   this   is   a   long first message   ")
    assert title == "this is a long first message"


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


@pytest.mark.asyncio
async def test_get_next_action_prefers_active_goal_next_action(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())
    course_id = uuid.uuid4()
    goal = SimpleNamespace(
        id=uuid.uuid4(),
        title="Pass the final",
        next_action="Review chapter 3 weak points tonight.",
        target_date=datetime.now(timezone.utc),
    )
    db = MagicMock()
    db.execute = AsyncMock(return_value=_ScalarResult(goal))
    monkeypatch.setattr("routers.goals.get_course_or_404", AsyncMock())

    result = await get_next_action(course_id=course_id, user=user, db=db)

    assert result.source == "manual"
    assert result.goal_id == str(goal.id)
    assert "Review chapter 3 weak points tonight." in result.recommended_action


@pytest.mark.asyncio
async def test_get_next_action_falls_back_to_failed_task(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())
    course_id = uuid.uuid4()
    failed_task = SimpleNamespace(
        id=uuid.uuid4(),
        goal_id=None,
        title="Queued exam prep",
        task_type="exam_prep",
        status="failed",
    )
    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            _ScalarResult(None),  # active goal
            _ScalarResult(None),  # next assignment
            _ScalarResult(failed_task),  # failed task
        ]
    )
    monkeypatch.setattr("routers.goals.get_course_or_404", AsyncMock())
    monkeypatch.setattr("routers.goals.predict_forgetting", AsyncMock(return_value={"predictions": []}))

    result = await get_next_action(course_id=course_id, user=user, db=db)

    assert result.source == "task_failure"
    assert result.goal_id is None
    assert result.suggested_task_type == "exam_prep"


def test_validate_url_blocks_private_dns_resolution(monkeypatch):
    monkeypatch.setattr(
        "routers.upload.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (0, 0, 0, "", ("192.168.1.10", 0)),
        ],
    )

    with pytest.raises(ValidationError) as exc:
        _validate_url("https://example.com/notes")

    assert exc.value.status == 422
    assert "Internal URLs" in exc.value.message


def test_validate_url_allows_public_dns_resolution(monkeypatch):
    monkeypatch.setattr(
        "routers.upload.socket.getaddrinfo",
        lambda *args, **kwargs: [
            (0, 0, 0, "", ("93.184.216.34", 0)),
        ],
    )

    assert _validate_url("https://example.com/notes") == "https://example.com/notes"


@pytest.mark.asyncio
async def test_get_current_user_commits_local_user_creation(monkeypatch):
    monkeypatch.setattr("services.auth.dependency.settings.auth_enabled", False, raising=False)
    monkeypatch.setattr("services.auth.dependency.settings.deployment_mode", "single_user", raising=False)

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    user = await get_current_user(db=db, credentials=None)

    assert user.name == "Owner"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(user)


@pytest.mark.asyncio
async def test_resolve_chat_session_creates_new_session_record():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    session = await _resolve_chat_session(
        db=db,
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        scene_id="study_session",
        message="Help me understand chapter 3",
        session_id=None,
    )

    db.add.assert_called_once()
    db.flush.assert_awaited_once()
    assert session.scene_id == "study_session"
    assert session.title == "Help me understand chapter 3"


@pytest.mark.asyncio
async def test_resolve_chat_session_updates_existing_scene():
    existing_session = MagicMock(scene_id="study_session", title=None)
    result = MagicMock()
    result.scalar_one_or_none.return_value = existing_session

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()

    session = await _resolve_chat_session(
        db=db,
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        scene_id="exam_prep",
        message="Prepare me for the final exam",
        session_id=uuid.uuid4(),
    )

    db.flush.assert_awaited_once()
    assert session.scene_id == "exam_prep"
    assert session.title == "Prepare me for the final exam"


@pytest.mark.asyncio
async def test_derive_question_reuses_existing_diagnostic_pair():
    user = SimpleNamespace(id=uuid.uuid4())
    wrong_answer_id = uuid.uuid4()
    problem_id = uuid.uuid4()
    course_id = uuid.uuid4()
    content_node_id = uuid.uuid4()

    wa = SimpleNamespace(
        id=wrong_answer_id,
        problem_id=problem_id,
        user_answer="B",
        correct_answer="A",
        error_category="conceptual",
        knowledge_points=["limits"],
    )
    problem = SimpleNamespace(
        id=problem_id,
        course_id=course_id,
        content_node_id=content_node_id,
        question="What is the limit?",
        question_type="mc",
        problem_metadata={},
        knowledge_points=["limits"],
    )
    existing_diag = SimpleNamespace(
        id=uuid.uuid4(),
        question="Simplified limit question",
        question_type="mc",
        options={"A": "1", "B": "2"},
        problem_metadata={
            "wrong_answer_id": str(wrong_answer_id),
            "simplifications_made": ["Removed distractor"],
            "core_concept_preserved": "limits",
        },
        created_at=None,
    )

    first_result = MagicMock()
    first_result.one_or_none.return_value = (wa, problem)
    second_result = MagicMock()
    second_result.scalars.return_value.all.return_value = [existing_diag]

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[first_result, second_result])

    response = await derive_question(wrong_answer_id, user=user, db=db)

    assert response["problem_id"] == str(existing_diag.id)
    assert response["question"] == "Simplified limit question"
    db.add.assert_not_called()


@pytest.mark.asyncio
async def test_diagnose_from_pair_reuses_existing_diagnosis():
    user = SimpleNamespace(id=uuid.uuid4())
    wa = SimpleNamespace(
        id=uuid.uuid4(),
        diagnosis="trap_vulnerability",
        mastered=True,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = wa

    db = MagicMock()
    db.execute = AsyncMock(return_value=result)

    response = await diagnose_from_pair(wa.id, user=user, db=db)

    assert response["diagnosis"] == "trap_vulnerability"
    assert response["original_correct"] is True
    db.commit.assert_not_called()
