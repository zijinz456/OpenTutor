"""Unit tests for service layer — no database or HTTP required."""

import asyncio
import json
import math
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# ── Search: RRF scoring ──

from services.search.scoring import _document_signal_score, _tokenize_query, rrf_score, RRF_K
from services.search.fusion import hybrid_search
from services.search.rag_fusion import rag_fusion_search
from services.agent.task_planner import execute_plan_step
from services.agent.state import AgentContext, IntentType, TaskPhase
from models.agent_task import AgentTask
from models.memory import ConversationMemory
from models.preference import UserPreference
from models.study_goal import StudyGoal
from models.user import User
from services.activity import engine as activity_engine
from services.activity.task_types import (
    APPROVAL_PENDING,
    APPROVAL_REQUIRED_STATUS,
    CANCEL_REQUESTED_STATUS,
    infer_task_policy,
)
from services.agent.verifier import verify_and_repair
from services.scheduler import engine as scheduler_engine
from routers.preferences_crud import build_learning_profile_summary
from services.preference.engine import resolve_preferences


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


def test_document_signal_score_prefers_phrase_and_title_matches():
    stronger = _document_signal_score(
        {
            "title": "Common Pitfalls in Binary Search",
            "content": "Off-by-one errors and sorted-array assumptions are common pitfalls in binary search.",
            "level": 2,
            "source": "keyword",
            "score": 4.0,
        },
        "common pitfalls in binary search",
        _tokenize_query("common pitfalls in binary search"),
    )
    weaker = _document_signal_score(
        {
            "title": "Algorithm Notes",
            "content": "This section mentions binary search once.",
            "level": 2,
            "source": "vector",
            "score": 1.0,
        },
        "common pitfalls in binary search",
        _tokenize_query("common pitfalls in binary search"),
    )

    assert stronger > weaker


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


# ── Ingestion: filename classification ──

from services.ingestion.pipeline import classify_by_filename, detect_mime_type
from services.parser.quiz import _normalize_problem_metadata, prepare_generated_questions
from services.practice.annotation import normalize_problem_annotation, parse_question_array, validate_question_payload
from services.ingestion.document_loader_html import extract_title, get_text_from_soup
from services.evaluation.eval_response import eval_response


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
    from services.activity import engine_lifecycle
    monkeypatch.setattr(engine_lifecycle, "async_session", lambda: _FakeSessionContext(session))
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

    from services.scheduler import engine_jobs_maintenance, engine_helpers
    monkeypatch.setattr(engine_jobs_maintenance, "async_session", lambda: _FakeSessionContext(session))
    monkeypatch.setattr(engine_helpers, "async_session", lambda: _FakeSessionContext(session))
    submit_task = AsyncMock()
    push_notification = AsyncMock()
    monkeypatch.setattr(engine_jobs_maintenance, "submit_task", submit_task)
    monkeypatch.setattr(engine_jobs_maintenance, "_push_notification", push_notification)

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


def test_validate_question_payload_backfills_missing_metadata_fields():
    validation = validate_question_payload(
        {
            "question_type": "short_answer",
            "question": "Explain why binary search requires sorted data.",
            "correct_answer": "Because the midpoint comparison only rules out half the array when the order is known.",
            "explanation": "Sorted order is what makes each comparison eliminate half of the remaining search space.",
            "problem_metadata": {"core_concept": "main idea", "source_section": ""},
        },
        title="Binary Search Basics",
        source="generated",
    )

    assert validation.is_valid is True
    assert validation.question is not None
    assert validation.question["problem_metadata"]["core_concept"] == "binary search requires sorted data"
    assert validation.question["problem_metadata"]["source_section"] == "Binary Search Basics"


def test_validate_question_payload_rejects_missing_quiz_answers():
    validation = validate_question_payload(
        {
            "question_type": "mc",
            "question": "What condition must hold before using binary search?",
            "options": {"A": "Sorted", "B": "Random", "C": "Prime sized", "D": "Recursive"},
            "correct_answer": "",
            "explanation": "",
        },
        title="Binary Search",
    )

    assert validation.is_valid is False
    assert any("correct_answer" in error for error in validation.errors)
    assert any("explanation" in error for error in validation.errors)


def test_validate_question_payload_rejects_bloom_level_mismatch_for_difficulty():
    validation = validate_question_payload(
        {
            "question_type": "mc",
            "question": "Which invariant keeps binary search correct?",
            "options": {
                "A": "The target stays inside the remaining interval",
                "B": "The midpoint never changes",
                "C": "The array becomes unsorted",
                "D": "Every element is unique",
            },
            "correct_answer": "A",
            "explanation": "The interval invariant is the basic idea that justifies each elimination step.",
            "difficulty_layer": 1,
            "problem_metadata": {
                "core_concept": "binary search invariant",
                "bloom_level": "create",
            },
        },
        title="Binary Search Basics",
    )

    assert validation.is_valid is False
    assert any("bloom_level" in error for error in validation.errors)


@pytest.mark.asyncio
async def test_prepare_generated_questions_drops_duplicates_and_invalid_items():
    prepared = await prepare_generated_questions(
        raw_content=json.dumps(
            [
                {
                    "question_type": "mc",
                    "question": "What must be true before binary search works?",
                    "options": {"A": "Sorted data", "B": "Unique data", "C": "Prime size", "D": "Recursion"},
                    "correct_answer": "A",
                    "explanation": "Binary search assumes sorted order.",
                    "problem_metadata": {"core_concept": "binary search prerequisite"},
                },
                {
                    "question_type": "mc",
                    "question": "What must be true before binary search works?",
                    "options": {"A": "Sorted data", "B": "Unique data", "C": "Prime size", "D": "Recursion"},
                    "correct_answer": "A",
                    "explanation": "Binary search assumes sorted order.",
                    "problem_metadata": {"core_concept": "binary search prerequisite"},
                },
                {
                    "question_type": "short_answer",
                    "question": "Name the invariant.",
                    "correct_answer": "",
                    "explanation": "",
                },
            ]
        ),
        title="Binary Search Basics",
    )

    assert len(prepared.questions) == 1
    assert prepared.discarded_count == 2


@pytest.mark.asyncio
async def test_prepare_generated_questions_filters_near_duplicates_and_overrepresented_types():
    prepared = await prepare_generated_questions(
        raw_content=json.dumps(
            [
                {
                    "question_type": "mc",
                    "question": "What must be true before binary search works?",
                    "options": {"A": "Sorted data", "B": "Unique data", "C": "Prime size", "D": "Recursion"},
                    "correct_answer": "A",
                    "explanation": "Binary search assumes sorted order.",
                    "problem_metadata": {"core_concept": "binary search prerequisite"},
                },
                {
                    "question_type": "mc",
                    "question": "Before binary search works, what must be true?",
                    "options": {"A": "Sorted data", "B": "Unique data", "C": "Prime size", "D": "Recursion"},
                    "correct_answer": "A",
                    "explanation": "Sorted order is the key prerequisite.",
                    "problem_metadata": {"core_concept": "binary search prerequisite"},
                },
                {
                    "question_type": "mc",
                    "question": "Which boundary update keeps binary search moving left?",
                    "options": {"A": "right = mid - 1", "B": "left = mid + 1", "C": "left = 0", "D": "mid = 0"},
                    "correct_answer": "A",
                    "explanation": "When the target is smaller, the right boundary moves left of mid.",
                    "problem_metadata": {"core_concept": "boundary update"},
                },
                {
                    "question_type": "mc",
                    "question": "What does the midpoint comparison tell you in binary search?",
                    "options": {"A": "Which half can be discarded", "B": "Whether the array is unique", "C": "That recursion is required", "D": "That sorting is optional"},
                    "correct_answer": "A",
                    "explanation": "The midpoint comparison tells you which half cannot contain the target.",
                    "problem_metadata": {"core_concept": "midpoint comparison"},
                },
                {
                    "question_type": "mc",
                    "question": "Why is a sorted array necessary for binary search?",
                    "options": {"A": "So each comparison rules out half the range", "B": "So indices start at one", "C": "So every value is different", "D": "So recursion becomes mandatory"},
                    "correct_answer": "A",
                    "explanation": "Ordering is what makes halving the search space valid.",
                    "problem_metadata": {"core_concept": "sorted prerequisite"},
                },
                {
                    "question_type": "tf",
                    "question": "Binary search can discard half the array after each comparison.",
                    "correct_answer": "True",
                    "explanation": "That halving step is the central efficiency gain.",
                    "problem_metadata": {"core_concept": "binary search efficiency"},
                },
            ]
        ),
        title="Binary Search Basics",
    )

    assert len(prepared.questions) == 4
    assert prepared.discarded_count == 2
    assert any("near-duplicate" in warning for warning in prepared.warnings)
    assert any("keep the quiz batch diverse" in warning for warning in prepared.warnings)


def test_extract_title_prefers_meta_title_and_strips_duplicate_heading():
    from bs4 import BeautifulSoup

    html = """
    <html>
      <head>
        <meta property="og:title" content="Binary Search Notes" />
        <title>binary-search.html</title>
      </head>
      <body>
        <h1>Binary Search Notes</h1>
        <p>Binary search works on sorted arrays.</p>
      </body>
    </html>
    """
    soup = BeautifulSoup(html, "lxml")
    title = extract_title(soup, url="https://example.com/binary-search.html")
    text = get_text_from_soup(soup, title=title)

    assert title == "Binary Search Notes"
    assert text.startswith("Binary search works on sorted arrays.")
    assert "binary-search.html" not in title


@pytest.mark.asyncio
async def test_eval_response_uses_shared_json_parser_for_wrapped_judge_output(monkeypatch):
    class _FakeJudge:
        provider_name = "deepseek"

        async def chat(self, *_args, **_kwargs):
            return (
                """```json
                {"correctness":{"score":5,"rationale":"good"},"relevance":{"score":4,"rationale":"on topic"},"helpfulness":{"score":4,"rationale":"clear"}}
                ```""",
                {},
            )

    monkeypatch.setattr("services.llm.router.get_llm_client", lambda *_args, **_kwargs: _FakeJudge())

    score = await eval_response(
        question="Why does binary search need sorted input?",
        response="It needs sorted data so each midpoint comparison can eliminate half the search space.",
        context="Binary search repeatedly halves a sorted search space.",
    )

    assert score.correctness == 5
    assert score.relevance == 4
    assert score.helpfulness == 4


# ── Embedding: registry pattern ──

def test_embedding_registry_raises_without_providers():
    """In eager mode, missing OpenAI/local providers should raise."""
    from services.embedding import registry
    from config import settings as real_settings

    original_key = real_settings.openai_api_key
    original_mode = real_settings.embedding_mode
    original_deepseek_key = real_settings.deepseek_api_key
    original_llm_provider = real_settings.llm_provider
    try:
        real_settings.openai_api_key = ""
        real_settings.deepseek_api_key = ""
        real_settings.llm_provider = "ollama"
        real_settings.embedding_mode = "eager"
        registry._provider = None
        with patch.dict("sys.modules", {"services.embedding.local": None}):
            with pytest.raises((RuntimeError, ImportError)):
                registry.get_embedding_provider()
    finally:
        real_settings.openai_api_key = original_key
        real_settings.embedding_mode = original_mode
        real_settings.deepseek_api_key = original_deepseek_key
        real_settings.llm_provider = original_llm_provider
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


@pytest.mark.asyncio
async def test_execute_plan_step_fails_when_verifier_rejects_output(monkeypatch):
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="review current progress",
    )
    ctx.response = "You are definitely ready. Trust me."
    ctx.delegated_agent = "assessment"
    ctx.metadata["verifier"] = {
        "status": "failed",
        "code": "assessment_overstates_memory_evidence",
        "message": "Assessment answers must distinguish hard evidence from inference.",
        "repair_attempted": True,
    }

    async def fake_run_agent_turn(**_kwargs):
        return ctx

    monkeypatch.setattr("services.agent.orchestrator.run_agent_turn", fake_run_agent_turn)

    step_result = await execute_plan_step(
        step={
            "step_index": 0,
            "step_type": "assess_readiness",
            "title": "Assess readiness",
            "description": "Assess readiness",
            "depends_on": [],
        },
        previous_results=[],
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        db=MagicMock(),
        db_factory=MagicMock(),
    )

    assert step_result["success"] is False
    assert "assessment_overstates_memory_evidence" in (step_result["error"] or "")
    assert step_result["verifier"]["status"] == "failed"


@pytest.mark.asyncio
async def test_execute_plan_step_carries_verifier_diagnostics(monkeypatch):
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="explain binary search invariants",
    )
    ctx.response = "This answer is too generic."
    ctx.delegated_agent = "teaching"
    ctx.metadata["verifier"] = {
        "status": "failed",
        "code": "response_misses_requested_points",
        "message": "The answer did not cover enough of the requested points.",
        "repair_attempted": True,
    }
    ctx.metadata["verifier_diagnostics"] = {
        "request_coverage": 0.2,
        "evidence_coverage": 0.0,
        "request_overlap_terms": ["binary"],
        "evidence_overlap_terms": [],
    }

    async def fake_run_agent_turn(**_kwargs):
        return ctx

    monkeypatch.setattr("services.agent.orchestrator.run_agent_turn", fake_run_agent_turn)

    step_result = await execute_plan_step(
        step={
            "step_index": 0,
            "step_type": "summarize_content",
            "title": "Explain invariants",
            "description": "Explain invariants",
            "depends_on": [],
        },
        previous_results=[],
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        db=MagicMock(),
        db_factory=MagicMock(),
    )

    assert step_result["verifier_diagnostics"]["request_coverage"] == 0.2
    assert step_result["verifier_diagnostics"]["request_overlap_terms"] == ["binary"]


@pytest.mark.asyncio
async def test_execute_plan_step_rejects_non_actionable_study_plan(monkeypatch):
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="create study plan",
    )
    ctx.response = "You should probably study more and stay focused."
    ctx.delegated_agent = "planning"
    ctx.metadata["verifier"] = {
        "status": "pass",
        "code": "ok",
        "message": "Response satisfied verifier checks.",
        "repair_attempted": False,
    }

    async def fake_run_agent_turn(**_kwargs):
        return ctx

    monkeypatch.setattr("services.agent.orchestrator.run_agent_turn", fake_run_agent_turn)

    step_result = await execute_plan_step(
        step={
            "step_index": 0,
            "step_type": "build_study_plan",
            "title": "Build study plan",
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
    assert step_result["error"] == "The step did not produce a time-structured actionable plan."


@pytest.mark.asyncio
async def test_verifier_rejects_generic_nonanswer_for_learning_request():
    class _Agent:
        def get_llm_client(self):
            raise RuntimeError("repair should not run in this test")

        def build_system_prompt(self, _ctx):
            return "system"

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="Explain binary search invariants",
    )
    ctx.intent = IntentType.LEARN
    ctx.response = "I can help with that. Let's work through it together."

    verified = await verify_and_repair(ctx, _Agent())

    assert verified.metadata["verifier"]["status"] == "failed"
    assert verified.metadata["verifier"]["code"] == "response_does_not_address_request"


@pytest.mark.asyncio
async def test_verifier_records_acceptance_diagnostics_for_grounded_answer():
    class _Agent:
        def get_llm_client(self):
            raise RuntimeError("repair should not run in this test")

        def build_system_prompt(self, _ctx):
            return "system"

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="Explain binary search invariants and boundary updates",
    )
    ctx.intent = IntentType.LEARN
    ctx.content_docs = [
        {
            "title": "Binary Search Invariants",
            "content": "Keep the target inside the left/right bounds and update the boundaries after each comparison.",
        }
    ]
    ctx.response = (
        "The key invariant is that the target stays inside the current left/right boundary. "
        "Each comparison updates the boundary while preserving that invariant."
    )

    verified = await verify_and_repair(ctx, _Agent())

    assert verified.metadata["verifier"]["status"] == "pass"
    assert verified.metadata["verifier_diagnostics"]["request_coverage"] >= 0.3
    assert verified.metadata["verifier_diagnostics"]["evidence_coverage"] > 0


@pytest.mark.asyncio
async def test_verifier_catches_socratic_violation_direct_answer():
    """Tutor gives 'the answer is X' without guiding the student → flagged."""

    class _Agent:
        def get_llm_client(self):
            raise RuntimeError("should not repair in this test")

        def build_system_prompt(self, _ctx):
            return "system"

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="What is the present value formula?",
    )
    ctx.intent = IntentType.LEARN
    ctx.content_docs = [{"title": "Present Value", "content": "PV = FV / (1+r)^n"}]
    ctx.response = (
        "The answer is PV = FV / (1+r)^n. You divide the future value by "
        "the discount factor raised to the number of periods."
    )

    verified = await verify_and_repair(ctx, _Agent())
    assert verified.metadata["verifier"]["code"] == "socratic_violation_direct_answer"


@pytest.mark.asyncio
async def test_verifier_allows_socratic_answer_with_followup():
    """Tutor mentions 'the answer is' but follows up with a Socratic question → allowed."""

    class _Agent:
        def get_llm_client(self):
            raise RuntimeError("should not repair in this test")

        def build_system_prompt(self, _ctx):
            return "system"

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="What is the present value formula?",
    )
    ctx.intent = IntentType.LEARN
    ctx.content_docs = [{"title": "Present Value", "content": "PV = FV / (1+r)^n"}]
    ctx.response = (
        "Great question about the present value formula! Before I reveal it, "
        "let's think about what present value means conceptually. If you have a "
        "future value of money and you know the interest rate, what do you think "
        "you'd need to do to find its value today? Think about how the discount "
        "rate and the number of periods affect the formula. How would you approach "
        "discounting a future cash flow back to today's terms? The relationship "
        "between present value, future value, and the discount factor is the key."
    )

    verified = await verify_and_repair(ctx, _Agent())
    # Should pass because the response contains Socratic counter-patterns
    assert verified.metadata["verifier"]["code"] != "socratic_violation_direct_answer"


@pytest.mark.asyncio
async def test_hybrid_search_uses_signal_reranking(monkeypatch):
    async def fake_keyword_search(_db, _course_id, _query, limit=10):
        return [
            {
                "id": "generic",
                "title": "Algorithms",
                "content": "Binary search is mentioned briefly.",
                "level": 1,
                "score": 5.0,
                "source": "keyword",
            },
            {
                "id": "pitfalls",
                "title": "Common Pitfalls in Binary Search",
                "content": "Common pitfalls in binary search include off-by-one errors and unsorted arrays.",
                "level": 2,
                "score": 3.0,
                "source": "keyword",
            },
        ]

    async def fake_tree_search(_db, _course_id, _query, limit=5):
        return []

    async def fake_vector_search(_db, _course_id, _query, limit=10):
        return []

    monkeypatch.setattr("services.search.fusion.keyword_search", fake_keyword_search)
    monkeypatch.setattr("services.search.fusion.tree_search", fake_tree_search)
    monkeypatch.setattr("services.search.fusion.vector_search", fake_vector_search)

    results = await hybrid_search(None, uuid.uuid4(), "common pitfalls in binary search", limit=2)

    assert results[0]["id"] == "pitfalls"
    assert results[0]["hybrid_score"] > results[1]["hybrid_score"]


@pytest.mark.asyncio
async def test_hybrid_search_rewards_query_facet_coverage(monkeypatch):
    async def fake_keyword_search(_db, _course_id, _query, limit=10):
        return [
            {
                "id": "single-focus",
                "title": "Binary Search Invariants",
                "content": "Loop invariants keep the search interval valid.",
                "level": 1,
                "score": 5.0,
                "source": "keyword",
            },
            {
                "id": "two-facets",
                "title": "Binary Search Invariants and Off-by-One Errors",
                "content": "Track the invariant and watch off-by-one boundary updates.",
                "level": 2,
                "score": 4.0,
                "source": "keyword",
            },
        ]

    async def fake_tree_search(_db, _course_id, _query, limit=5):
        return []

    async def fake_vector_search(_db, _course_id, _query, limit=10):
        return []

    monkeypatch.setattr("services.search.fusion.keyword_search", fake_keyword_search)
    monkeypatch.setattr("services.search.fusion.tree_search", fake_tree_search)
    monkeypatch.setattr("services.search.fusion.vector_search", fake_vector_search)

    results = await hybrid_search(None, uuid.uuid4(), "binary search invariants and off-by-one errors", limit=2)

    assert results[0]["id"] == "two-facets"
    assert results[0]["facet_coverage"] > results[1]["facet_coverage"]
    assert "off-by-one errors" in " ".join(results[0]["matched_facets"]).lower()


@pytest.mark.asyncio
async def test_hybrid_search_aggregates_duplicate_section_hits(monkeypatch):
    async def fake_keyword_search(_db, _course_id, _query, limit=10):
        return [
            {
                "id": "section-a-1",
                "title": "Binary Search Invariants",
                "content": "Invariant overview and left/right bounds.",
                "level": 2,
                "parent_id": "section-a",
                "source_file": "week6.pdf",
                "score": 5.0,
                "source": "keyword",
            },
            {
                "id": "section-a-2",
                "title": "Binary Search Invariants",
                "content": "Boundary updates and off-by-one checks.",
                "level": 2,
                "parent_id": "section-a",
                "source_file": "week6.pdf",
                "score": 4.5,
                "source": "keyword",
            },
            {
                "id": "section-b-1",
                "title": "Merge Sort",
                "content": "Different topic.",
                "level": 2,
                "parent_id": "section-b",
                "source_file": "week6.pdf",
                "score": 4.0,
                "source": "keyword",
            },
        ]

    async def fake_tree_search(_db, _course_id, _query, limit=5):
        return []

    async def fake_vector_search(_db, _course_id, _query, limit=10):
        return []

    monkeypatch.setattr("services.search.fusion.keyword_search", fake_keyword_search)
    monkeypatch.setattr("services.search.fusion.tree_search", fake_tree_search)
    monkeypatch.setattr("services.search.fusion.vector_search", fake_vector_search)

    results = await hybrid_search(None, uuid.uuid4(), "binary search invariants and boundary updates", limit=3)

    assert len(results) == 2
    assert results[0]["section_hit_count"] == 2
    assert set(results[0]["supporting_hit_ids"]) == {"section-a-1"} or set(results[0]["supporting_hit_ids"]) == {"section-a-2"}
    assert "evidence_summary" in results[0]
    assert results[0]["evidence_summary"]


@pytest.mark.asyncio
async def test_rag_fusion_rewards_results_seen_across_multiple_queries(monkeypatch):
    async def fake_generate_query_variants(_query, n=3, course_context=""):
        return ["binary search mistakes", "sorted array requirement"]

    async def fake_hybrid_search(_db, _course_id, query, limit=5):
        if query == "binary search basics":
            return [
                {"id": "shared", "title": "Binary Search Basics", "content": "sorted array requirement", "hybrid_score": 0.06},
                {"id": "single", "title": "Single Hit", "content": "misc", "hybrid_score": 0.08},
            ]
        if query == "binary search mistakes":
            return [
                {"id": "shared", "title": "Binary Search Basics", "content": "mistakes", "hybrid_score": 0.05},
            ]
        return [
            {"id": "shared", "title": "Binary Search Basics", "content": "sorted", "hybrid_score": 0.05},
        ]

    monkeypatch.setattr("services.search.rag_fusion.generate_query_variants", fake_generate_query_variants)
    monkeypatch.setattr("services.search.rag_fusion.hybrid_search", fake_hybrid_search)

    results = await rag_fusion_search(None, uuid.uuid4(), "binary search basics", limit=2)

    assert results[0]["id"] == "shared"
    assert results[0]["query_count"] == 3


@pytest.mark.asyncio
async def test_rag_fusion_uses_query_decomposition_without_llm_variants(monkeypatch):
    async def fake_generate_query_variants(_query, n=3, course_context=""):
        return []

    async def fake_hybrid_search(_db, _course_id, query, limit=5):
        if query == "binary search invariants and off-by-one errors":
            return [
                {"id": "generic", "title": "Binary Search", "content": "binary search overview", "hybrid_score": 0.09, "coverage_score": 0.0},
            ]
        if "invariants" in query:
            return [
                {"id": "shared-facet", "title": "Binary Search Invariants", "content": "invariant details", "hybrid_score": 0.05, "coverage_score": 0.02},
            ]
        return [
            {"id": "shared-facet", "title": "Binary Search Invariants", "content": "off-by-one details", "hybrid_score": 0.05, "coverage_score": 0.02},
        ]

    monkeypatch.setattr("services.search.rag_fusion.generate_query_variants", fake_generate_query_variants)
    monkeypatch.setattr("services.search.rag_fusion.hybrid_search", fake_hybrid_search)

    results = await rag_fusion_search(None, uuid.uuid4(), "binary search invariants and off-by-one errors", limit=2)

    assert results[0]["id"] == "shared-facet"
    assert results[0]["query_variant_total"] >= 2
