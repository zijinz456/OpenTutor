import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

from libs.exceptions import NotFoundError, ValidationError
from routers.chat import _build_session_title, _resolve_chat_session
from routers.goals import get_next_action, queue_next_action
from routers.preferences import _normalize_preference_value
from routers.upload import _validate_url
from routers.wrong_answers import derive_question, diagnose_from_pair
from services.agent.agenda_ranking import AgendaDecision
from services.agent.agenda_signals import AgendaSignal
from services.auth.dependency import get_current_user
from services.llm.local_config import get_llm_runtime_config, update_llm_runtime_config
from services.llm import router as llm_router
from services.health import _local_beta_readiness
from services.migrations import bootstrap_alembic_version_table, summarize_migration_state


def test_normalize_preference_value_basic_mappings():
    assert _normalize_preference_value("detail_level", "moderate") == "balanced"
    assert _normalize_preference_value("language", "zh-cn") == "zh"
    assert _normalize_preference_value("explanation_style", "analogy") == "example_heavy"
    assert _normalize_preference_value("note_format", "table") == "table"


def test_llm_router_falls_back_to_mock_without_keys(monkeypatch):
    monkeypatch.setattr(llm_router.settings, "openai_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "anthropic_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "deepseek_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "openrouter_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "gemini_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "groq_api_key", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "llm_provider", "openai", raising=False)
    monkeypatch.setattr(llm_router.settings, "custom_llm_base_url", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "use_litellm", False, raising=False)
    monkeypatch.setattr(llm_router.settings, "litellm_model", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "llm_required", False, raising=False)
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
    monkeypatch.setattr(llm_router.settings, "llm_provider", "openai", raising=False)
    monkeypatch.setattr(llm_router.settings, "custom_llm_base_url", "", raising=False)
    monkeypatch.setattr(llm_router.settings, "use_litellm", False, raising=False)
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


def test_summarize_migration_state_requires_alembic_tracking():
    state = summarize_migration_state(
        table_names={"users", "courses"},
        current_heads=[],
        expected_heads=["20260306_0017"],
    )

    assert state.schema_ready is False
    assert state.migration_required is True
    assert state.migration_status == "version_table_missing"
    assert state.alembic_version_present is False


def test_summarize_migration_state_accepts_current_head():
    state = summarize_migration_state(
        table_names={"users", "alembic_version"},
        current_heads=["20260306_0017"],
        expected_heads=["20260306_0017"],
    )

    assert state.schema_ready is True
    assert state.migration_required is False
    assert state.migration_status == "ready"
    assert state.alembic_version_present is True


def test_bootstrap_alembic_version_table_stamps_when_schema_exists(monkeypatch):
    monkeypatch.setattr("services.migrations.get_expected_migration_heads", lambda: ["20260307_0019"])
    engine = sa.create_engine("sqlite:///:memory:")

    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))

        stamped = bootstrap_alembic_version_table(conn)
        versions = conn.execute(sa.text("SELECT version_num FROM alembic_version")).fetchall()

    assert stamped == ["20260307_0019"]
    assert versions == [("20260307_0019",)]


def test_local_beta_readiness_blocks_degraded_llm():
    migration_state = summarize_migration_state(
        table_names={"users", "alembic_version"},
        current_heads=["20260306_0017"],
        expected_heads=["20260306_0017"],
    )

    blockers, warnings = _local_beta_readiness(
        db_ok=True,
        migration_state=migration_state,
        llm_status="degraded",
        sandbox_available=True,
    )

    assert blockers == ["llm_unhealthy"]
    assert warnings == []


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _serialized_task_payload(
    *,
    task_id: str,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
    goal_id: uuid.UUID | None,
    task_type: str,
    title: str,
    summary: str | None,
    metadata_json: dict | None = None,
) -> dict:
    return {
        "id": task_id,
        "user_id": str(user_id),
        "course_id": str(course_id),
        "goal_id": str(goal_id) if goal_id else None,
        "task_type": task_type,
        "status": "queued",
        "title": title,
        "summary": summary,
        "source": "agenda",
        "input_json": {},
        "metadata_json": metadata_json,
        "result_json": None,
        "error_message": None,
        "attempts": 0,
        "max_attempts": 2,
        "requires_approval": False,
        "task_kind": "read_only",
        "risk_level": "low",
        "approval_status": "not_required",
        "approval_reason": None,
        "approval_action": None,
        "checkpoint_json": None,
        "step_results": [],
        "provenance": None,
        "approved_at": None,
        "started_at": None,
        "cancel_requested_at": None,
        "created_at": None,
        "updated_at": None,
        "completed_at": None,
    }


@pytest.mark.asyncio
async def test_get_next_action_prefers_active_goal_next_action(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())
    course_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    decision = AgendaDecision(
        action="submit",
        signal=AgendaSignal(
            signal_type="active_goal",
            user_id=user.id,
            course_id=course_id,
            entity_id=str(goal_id),
            title="Pass the final",
            urgency=90.0,
            detail={"next_action": "Review chapter 3 weak points tonight."},
        ),
        task_type="multi_step",
        task_title="Execute next step: Pass the final",
        task_summary="Review chapter 3 weak points tonight.",
        goal_id=goal_id,
        reason="Active goal has a concrete next action.",
    )
    monkeypatch.setattr("routers.goals.get_course_or_404", AsyncMock())
    monkeypatch.setattr("routers.goals.resolve_next_action", AsyncMock(return_value=decision))

    result = await get_next_action(course_id=course_id, user=user, db=MagicMock())

    assert result.source == "recent_goal"
    assert result.goal_id == str(goal_id)
    assert "Review chapter 3 weak points tonight." in result.recommended_action


@pytest.mark.asyncio
async def test_get_next_action_falls_back_to_failed_task(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())
    course_id = uuid.uuid4()
    failed_task_id = uuid.uuid4()
    decision = AgendaDecision(
        action="retry",
        signal=AgendaSignal(
            signal_type="failed_task",
            user_id=user.id,
            course_id=course_id,
            entity_id=str(failed_task_id),
            title="Queued exam prep",
            urgency=80.0,
            detail={"status": "failed", "task_type": "exam_prep"},
        ),
        task_type="exam_prep",
        task_title="Recover: Queued exam prep",
        existing_task_id=failed_task_id,
        reason="Most recent durable task did not finish; recovery is more valuable than starting new work.",
    )
    monkeypatch.setattr("routers.goals.get_course_or_404", AsyncMock())
    monkeypatch.setattr("routers.goals.resolve_next_action", AsyncMock(return_value=decision))

    result = await get_next_action(course_id=course_id, user=user, db=MagicMock())

    assert result.source == "task_failure"
    assert result.goal_id is None
    assert result.suggested_task_type == "exam_prep"


@pytest.mark.asyncio
async def test_queue_next_action_from_active_goal_returns_multi_step_task(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())
    course_id = uuid.uuid4()
    goal_id = uuid.uuid4()
    queued_task = object()
    decision = AgendaDecision(
        action="submit",
        signal=AgendaSignal(
            signal_type="active_goal",
            user_id=user.id,
            course_id=course_id,
            entity_id=str(goal_id),
            title="Pass the final",
            urgency=90.0,
            detail={"next_action": "Review weak points from chapter 3 tonight."},
        ),
        task_type="multi_step",
        task_title="Execute next step: Pass the final",
        task_summary="Review weak points from chapter 3 tonight.",
        goal_id=goal_id,
        reason="Active goal has a concrete next action.",
    )

    serialized = _serialized_task_payload(
        task_id=str(uuid.uuid4()),
        user_id=user.id,
        course_id=course_id,
        goal_id=goal_id,
        task_type="multi_step",
        title="Execute next step: Pass the final",
        summary="Review weak points from chapter 3 tonight.",
        metadata_json={"agenda_decision": {"goal_id": str(goal_id), "reason": decision.reason}},
    )

    monkeypatch.setattr("routers.goals.get_course_or_404", AsyncMock())
    monkeypatch.setattr("routers.goals.resolve_next_action", AsyncMock(return_value=decision))
    queue_mock = AsyncMock(return_value=queued_task)
    monkeypatch.setattr("routers.goals.queue_decision", queue_mock)
    monkeypatch.setattr("routers.goals.serialize_task", lambda _task: serialized)

    result = await queue_next_action(course_id=course_id, user=user, db=MagicMock())

    assert result.task_type == "multi_step"
    assert result.goal_id == str(goal_id)
    assert result.title == "Execute next step: Pass the final"
    assert result.summary == "Review weak points from chapter 3 tonight."
    assert result.metadata_json["agenda_decision"]["reason"] == "Active goal has a concrete next action."
    queue_mock.assert_awaited_once()
    call = queue_mock.await_args
    assert call.args[0] is decision
    assert call.kwargs["user_id"] == user.id
    assert call.kwargs["course_id"] == course_id


@pytest.mark.asyncio
async def test_queue_next_action_retries_failed_task_and_clears_previous_error(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())
    course_id = uuid.uuid4()
    failed_task_id = uuid.uuid4()
    queued_task = object()
    decision = AgendaDecision(
        action="retry",
        signal=AgendaSignal(
            signal_type="failed_task",
            user_id=user.id,
            course_id=course_id,
            entity_id=str(failed_task_id),
            title="Queued exam prep",
            urgency=80.0,
            detail={"status": "failed", "task_type": "exam_prep"},
        ),
        task_type="exam_prep",
        task_title="Recover: Queued exam prep",
        existing_task_id=failed_task_id,
        reason="Most recent durable task did not finish; recovery is more valuable than starting new work.",
    )

    serialized = _serialized_task_payload(
        task_id=str(failed_task_id),
        user_id=user.id,
        course_id=course_id,
        goal_id=None,
        task_type="exam_prep",
        title="Queued exam prep",
        summary="Task failed previously.",
    )

    monkeypatch.setattr("routers.goals.get_course_or_404", AsyncMock())
    monkeypatch.setattr("routers.goals.resolve_next_action", AsyncMock(return_value=decision))
    queue_mock = AsyncMock(return_value=queued_task)
    monkeypatch.setattr("routers.goals.queue_decision", queue_mock)
    monkeypatch.setattr("routers.goals.serialize_task", lambda _task: serialized)

    result = await queue_next_action(course_id=course_id, user=user, db=MagicMock())

    assert result.id == str(failed_task_id)
    assert result.task_type == "exam_prep"
    assert result.status == "queued"
    assert result.attempts == 0
    assert result.error_message is None
    queue_mock.assert_awaited_once()


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


def test_validate_url_allows_configured_scrape_fixture_host(monkeypatch):
    monkeypatch.setattr("routers.upload.settings.scrape_fixture_dir", "/tmp/scrape-fixtures", raising=False)

    assert _validate_url("https://opentutor-e2e.local/binary-search") == "https://opentutor-e2e.local/binary-search"


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
    request = SimpleNamespace(state=SimpleNamespace())

    user = await get_current_user(request=request, db=db, credentials=None)

    assert user.name == "Owner"
    db.add.assert_called_once()
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once_with(user)
    assert request.state.user_id == str(user.id)
    assert request.state.deployment_mode == "single_user"


@pytest.mark.asyncio
async def test_get_current_user_returns_schema_hint_when_users_table_missing(monkeypatch):
    monkeypatch.setattr("services.auth.dependency.settings.auth_enabled", False, raising=False)
    monkeypatch.setattr("services.auth.dependency.settings.deployment_mode", "single_user", raising=False)

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=ProgrammingError(
            "SELECT users.id FROM users LIMIT 1",
            None,
            Exception('relation "users" does not exist'),
        )
    )

    with pytest.raises(HTTPException) as exc:
        await get_current_user(db=db, credentials=None)

    assert exc.value.status_code == 503
    assert "alembic upgrade head" in exc.value.detail


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
