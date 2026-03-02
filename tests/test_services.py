"""Unit tests for service layer — no database or HTTP required."""

import math
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# ── Search: RRF scoring ──

from services.search.hybrid import _tokenize_query, rrf_score, RRF_K
from services.agent.task_planner import execute_plan_step
from services.agent.state import AgentContext, TaskPhase
from models.agent_task import AgentTask
from models.memory import ConversationMemory
from models.preference import UserPreference
from models.study_goal import StudyGoal
from models.user import User
from services.activity import engine as activity_engine
from services.activity.tasks import (
    APPROVAL_PENDING,
    APPROVAL_REQUIRED_STATUS,
    CANCEL_REQUESTED_STATUS,
    infer_task_policy,
)
from services.audit import record_audit_log
from services.scheduler import engine as scheduler_engine
from routers.preferences import build_learning_profile_summary
from services.preference.engine import resolve_preferences
from services.scene.policy import decide_scene_policy_from_features


def test_rrf_score_formula():
    assert rrf_score(1) == pytest.approx(1 / (RRF_K + 1))
    assert rrf_score(10) == pytest.approx(1 / (RRF_K + 10))
    assert rrf_score(1) > rrf_score(2) > rrf_score(10)


def test_rrf_score_monotonically_decreasing():
    scores = [rrf_score(r) for r in range(1, 20)]
    for i in range(len(scores) - 1):
        assert scores[i] > scores[i + 1]


def test_tokenize_query_handles_ascii_terms():
    tokens = _tokenize_query("binary search invariant proof")

    assert "binary" in tokens
    assert "search" in tokens
    assert "invariant" in tokens
    assert "proof" in tokens


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
        "exam_prep": "help me prepare for the final exam",
        "review_drill": "review my wrong answers",
        "assignment": "homework problem",
        "note_organize": "help me organize my notes",
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


def test_learning_profile_summary_groups_memory_types():
    memories = [
        ConversationMemory(summary="Strong at binary search invariants", memory_type="skill"),
        ConversationMemory(summary="Still confuses heap push/pop order", memory_type="error"),
        ConversationMemory(summary="Prefers worked examples before abstractions", memory_type="preference"),
    ]

    summary = build_learning_profile_summary(memories)

    assert "Strong at binary search invariants" in summary.strength_areas
    assert "Still confuses heap push/pop order" in summary.weak_areas
    assert "Still confuses heap push/pop order" in summary.recurring_errors
    assert "Prefers worked examples before abstractions" in summary.inferred_habits


class _ScalarListResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class _PreferenceSession:
    def __init__(self, prefs):
        self.prefs = prefs

    async def execute(self, _query):
        return _ScalarListResult(self.prefs)


@pytest.mark.asyncio
async def test_resolve_preferences_skips_dismissed_entries():
    user_id = uuid.uuid4()
    active_pref = UserPreference(
        user_id=user_id,
        dimension="detail_level",
        value="concise",
        scope="global",
    )
    dismissed_pref = UserPreference(
        user_id=user_id,
        dimension="note_format",
        value="table",
        scope="global",
        dismissed_at=datetime.now(timezone.utc),
    )

    resolved = await resolve_preferences(_PreferenceSession([active_pref, dismissed_pref]), user_id)

    assert resolved.preferences["detail_level"] == "concise"
    assert resolved.preferences["note_format"] == "bullet_point"
    assert resolved.sources["note_format"] == "system_default"


def test_scene_policy_decision_exposes_strategy_bundle():
    features = {
        "matched_cues": {
            "study_session": [],
            "exam_prep": ["final"],
            "assignment": [],
            "review_drill": ["wrong answers"],
            "note_organize": [],
        },
        "upcoming_assignments": 1,
        "unmastered_wrong_answers": 4,
        "low_mastery_count": 3,
        "content_nodes": 12,
        "active_tab": "review",
        "course_active_scene": "study_session",
        "active_goal_title": "Ace the final",
        "active_goal_next_action": "Review wrong answers tonight",
        "active_goal_target_days": 4,
        "nearest_deadline_days": 2,
        "recent_failed_tasks": 1,
        "pending_approval_count": 0,
        "running_task_count": 0,
        "urgent_forgetting_count": 2,
        "warning_forgetting_count": 1,
    }

    decision = decide_scene_policy_from_features(features=features, current_scene="study_session")

    assert decision.scene_id in {"review_drill", "exam_prep", "assignment"}
    assert decision.expected_benefit
    assert decision.reversible_action
    assert decision.layout_policy
    assert decision.reasoning_policy
    assert decision.workflow_policy


def test_task_policy_requires_approval_for_persistent_code_execution():
    policy = infer_task_policy(
        "code_execution",
        {"code": "print('hi')", "persist": True, "output_path": "/tmp/out.txt"},
        requires_approval=False,
        title="Persist code output",
    )

    assert policy.requires_approval is True
    assert policy.task_kind == "external_side_effect"
    assert policy.risk_level == "high"
    assert "persist output" in (policy.approval_reason or "")
    assert "write" in (policy.approval_action or "").lower()


def test_task_policy_keeps_read_only_code_execution_without_approval():
    policy = infer_task_policy(
        "code_execution",
        {"code": "print(sum([1,2,3]))"},
        requires_approval=False,
        title="Read-only code run",
    )

    assert policy.requires_approval is False
    assert policy.task_kind == "read_only"
    assert policy.risk_level == "low"
    assert policy.approval_reason is None


class _AuditSession:
    def __init__(self):
        self.added = []
        self.flushes = 0

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1


@pytest.mark.asyncio
async def test_record_audit_log_creates_row():
    session = _AuditSession()
    actor_user_id = uuid.uuid4()
    task_id = uuid.uuid4()

    row = await record_audit_log(
        session,
        actor_user_id=actor_user_id,
        task_id=task_id,
        tool_name="run_code",
        action_kind="task_execute_complete",
        approval_status="approved",
        outcome="completed",
        details_json={"backend": "container"},
    )

    assert row.actor_user_id == actor_user_id
    assert row.task_id == task_id
    assert row.tool_name == "run_code"
    assert row.action_kind == "task_execute_complete"
    assert session.flushes == 1
    assert session.added and session.added[0] is row


class _ScalarResult:
    def __init__(self, task):
        self._task = task

    def scalar_one_or_none(self):
        return self._task


class _FakeSession:
    def __init__(self, task):
        self.task = task
        self.commits = 0
        self.refreshes = 0
        self.added = []
        self.flushes = 0

    async def execute(self, _query):
        return _ScalarResult(self.task)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1

    async def commit(self):
        self.commits += 1

    async def refresh(self, _task):
        self.refreshes += 1


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _patch_task_session(monkeypatch, task: AgentTask) -> _FakeSession:
    session = _FakeSession(task)
    monkeypatch.setattr(activity_engine, "async_session", lambda: _FakeSessionContext(session))
    return session


class _ScalarCollectionResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class _RowCollectionResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _SchedulerSession:
    def __init__(self, user: User):
        self.user = user
        self.goals: list[StudyGoal] = []
        self.tasks: list[AgentTask] = []

    async def execute(self, query):
        first_col = query.column_descriptions[0]
        if first_col.get("name") == "id" and first_col.get("entity") is User:
            return _RowCollectionResult([(self.user.id,)])
        entity = query.column_descriptions[0].get("entity")
        if entity is User:
            return _ScalarCollectionResult([self.user])
        if entity is StudyGoal:
            return _ScalarCollectionResult(self.goals)
        if entity is AgentTask:
            return _ScalarCollectionResult(self.tasks[:1])
        return _ScalarCollectionResult([])

    def add(self, obj):
        if isinstance(obj, StudyGoal):
            if obj.id is None:
                obj.id = uuid.uuid4()
            self.goals.append(obj)

    async def commit(self):
        return None

    async def refresh(self, _obj):
        return None


@pytest.mark.asyncio
async def test_reject_task_then_retry_resets_approval(monkeypatch):
    user_id = uuid.uuid4()
    task = AgentTask(
        id=uuid.uuid4(),
        user_id=user_id,
        course_id=None,
        task_type="exam_prep",
        status=APPROVAL_REQUIRED_STATUS,
        title="Approval gated task",
        source="workflow",
        requires_approval=True,
        attempts=1,
        max_attempts=2,
    )
    _patch_task_session(monkeypatch, task)

    rejected = await activity_engine.reject_task(task.id, user_id)
    assert rejected is task
    assert task.status == "rejected"
    assert task.approval_status == "rejected"
    assert task.error_message == "Rejected before execution."
    assert task.approved_at is None

    retried = await activity_engine.retry_task(task.id, user_id)
    assert retried is task
    assert task.status == APPROVAL_REQUIRED_STATUS
    assert task.approval_status == APPROVAL_PENDING
    assert task.attempts == 0
    assert task.result_json is None
    assert task.checkpoint_json is None
    assert task.step_results_json is None


@pytest.mark.asyncio
async def test_cancel_running_task_and_resume_from_cancelled(monkeypatch):
    user_id = uuid.uuid4()
    task = AgentTask(
        id=uuid.uuid4(),
        user_id=user_id,
        course_id=None,
        task_type="multi_step",
        status="running",
        title="Resumable task",
        source="workflow",
        requires_approval=False,
        result_json={"steps": [{"step_index": 0, "success": True}]},
        metadata_json={"plan_progress": [{"step_index": 0, "status": "completed"}]},
        attempts=1,
        max_attempts=2,
    )
    _patch_task_session(monkeypatch, task)

    cancelled = await activity_engine.cancel_task(task.id, user_id)
    assert cancelled is task
    assert task.status == CANCEL_REQUESTED_STATUS
    assert task.cancel_requested_at is not None

    task.status = "cancelled"
    resumed = await activity_engine.resume_task(task.id, user_id)
    assert resumed is task
    assert task.status == "resuming"
    assert task.cancel_requested_at is None
    assert task.result_json == {"steps": [{"step_index": 0, "success": True}]}


@pytest.mark.asyncio
async def test_resume_requires_approval_when_cancelled_before_approval(monkeypatch):
    user_id = uuid.uuid4()
    task = AgentTask(
        id=uuid.uuid4(),
        user_id=user_id,
        course_id=None,
        task_type="exam_prep",
        status="cancelled",
        title="Cancelled before approval",
        source="workflow",
        requires_approval=True,
        approved_at=None,
        attempts=0,
        max_attempts=2,
    )
    _patch_task_session(monkeypatch, task)

    resumed = await activity_engine.resume_task(task.id, user_id)
    assert resumed is task
    assert task.status == APPROVAL_REQUIRED_STATUS
    assert task.approval_status == APPROVAL_PENDING


@pytest.mark.asyncio
async def test_approve_invalid_state_raises_task_mutation_error(monkeypatch):
    user_id = uuid.uuid4()
    task = AgentTask(
        id=uuid.uuid4(),
        user_id=user_id,
        course_id=None,
        task_type="weekly_prep",
        status="completed",
        title="Already done",
        source="workflow",
        requires_approval=False,
        attempts=1,
        max_attempts=1,
    )
    _patch_task_session(monkeypatch, task)

    with pytest.raises(activity_engine.TaskMutationError):
        await activity_engine.approve_task(task.id, user_id)


@pytest.mark.asyncio
async def test_weekly_scheduler_enqueues_durable_task_and_creates_goal(monkeypatch):
    user = User(id=uuid.uuid4(), email="scheduler@test.dev", hashed_password="x")
    session = _SchedulerSession(user)

    monkeypatch.setattr(scheduler_engine, "async_session", lambda: _FakeSessionContext(session))
    submit_task = AsyncMock()
    push_notification = AsyncMock()
    monkeypatch.setattr(scheduler_engine, "submit_task", submit_task)
    monkeypatch.setattr(scheduler_engine, "_push_notification", push_notification)

    await scheduler_engine.weekly_prep_job()

    assert len(session.goals) == 1
    assert session.goals[0].metadata_json["goal_kind"] == "weekly_review"
    submit_task.assert_awaited_once()
    queued_kwargs = submit_task.await_args.kwargs
    assert queued_kwargs["task_type"] == "weekly_prep"
    assert queued_kwargs["source"] == "scheduler"
    assert queued_kwargs["goal_id"] == session.goals[0].id
    assert queued_kwargs["metadata_json"]["provenance"]["scheduler_trigger"] == "weekly_scheduler"
    push_notification.assert_awaited_once()


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


def test_scene_policy_prefers_review_drill_for_wrong_answer_recovery():
    features = {
        "matched_cues": {
            "study_session": [],
            "exam_prep": [],
            "assignment": [],
            "review_drill": ["wrong answers"],
            "note_organize": [],
        },
        "upcoming_assignments": 0,
        "unmastered_wrong_answers": 5,
        "low_mastery_count": 2,
        "content_nodes": 3,
        "active_tab": "review",
        "course_active_scene": "study_session",
        "active_goal_title": None,
        "active_goal_next_action": None,
        "active_goal_target_days": None,
        "nearest_deadline_days": None,
        "recent_failed_tasks": 0,
        "pending_approval_count": 0,
        "running_task_count": 0,
        "urgent_forgetting_count": 2,
        "warning_forgetting_count": 0,
    }

    decision = decide_scene_policy_from_features(features=features, current_scene="study_session")

    assert decision.scene_id == "review_drill"
    assert decision.switch_recommended is True
    assert "wrong answers" in decision.reason


def test_scene_policy_stays_put_when_running_task_exists():
    features = {
        "matched_cues": {
            "study_session": [],
            "exam_prep": [],
            "assignment": [],
            "review_drill": [],
            "note_organize": [],
        },
        "upcoming_assignments": 0,
        "unmastered_wrong_answers": 0,
        "low_mastery_count": 0,
        "content_nodes": 2,
        "active_tab": "activity",
        "course_active_scene": "study_session",
        "active_goal_title": None,
        "active_goal_next_action": None,
        "active_goal_target_days": None,
        "nearest_deadline_days": None,
        "recent_failed_tasks": 0,
        "pending_approval_count": 0,
        "running_task_count": 1,
        "urgent_forgetting_count": 0,
        "warning_forgetting_count": 0,
    }

    decision = decide_scene_policy_from_features(features=features, current_scene="study_session")

    assert decision.scene_id == "study_session"
    assert decision.switch_recommended is False


@pytest.mark.asyncio
async def test_execute_plan_step_marks_failed_context_as_unsuccessful(monkeypatch):
    failed_ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="help me study",
    )
    failed_ctx.response = ""
    failed_ctx.mark_failed("planner failed")

    async def fake_run_agent_turn(**_kwargs):
        return failed_ctx

    monkeypatch.setattr("services.agent.orchestrator.run_agent_turn", fake_run_agent_turn)

    step_result = await execute_plan_step(
        step={
            "step_index": 0,
            "step_type": "build_study_plan",
            "title": "Build plan",
            "description": "Create a study plan",
            "depends_on": [],
        },
        previous_results=[],
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        db=MagicMock(),
        db_factory=MagicMock(),
    )

    assert step_result["success"] is False
    assert step_result["error"] == "planner failed"
    assert step_result["input_message"] == "Create a study plan"
    assert step_result["tool_calls"] == []
    assert step_result["verifier"] is None
    assert step_result["provenance"] is None
