import json
import importlib
import importlib.util
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.agent.state import AgentContext, IntentType
from services.agent.turn_pipeline import build_provenance
from services.agent.orchestrator import orchestrate_stream, run_agent_turn, prepare_agent_turn
from services.search.hybrid import vector_search


class _DummyLLMClient:
    def __init__(self, usage: dict[str, int], supports_tools: bool = False):
        self._usage = usage
        if supports_tools:
            self.chat_with_tools = self._chat_with_tools

    def get_last_usage(self) -> dict[str, int]:
        return self._usage

    async def chat(self, *_args, **_kwargs):
        raise RuntimeError("no LLM in test")

    async def _chat_with_tools(self, *_args, **_kwargs):
        raise NotImplementedError


class _StreamingOnlyAgent:
    name = "dummy"

    def __init__(self, chunks: list[str], usage: dict[str, int] | None = None):
        self._chunks = chunks
        self._client = _DummyLLMClient(usage or {"input_tokens": 0, "output_tokens": 0})

    def get_llm_client(self):
        return self._client

    def build_system_prompt(self, _ctx):
        return "system"

    async def run(self, *_args, **_kwargs):
        raise AssertionError("run() should not be used for run_agent_turn")

    async def stream(self, ctx, _db):
        for chunk in self._chunks:
            yield chunk


class _FunctionCallingAgent(_StreamingOnlyAgent):
    def __init__(self, chunks: list[str], usage: dict[str, int]):
        super().__init__(chunks, usage=usage)
        self._client = _DummyLLMClient(usage, supports_tools=True)

    async def stream(self, ctx, _db):
        ctx.react_iterations = 1
        ctx.input_tokens = 10
        ctx.output_tokens = 4
        for chunk in self._chunks:
            yield chunk


class _RepairingLLMClient(_DummyLLMClient):
    async def chat(self, *_args, **_kwargs):
        return ("I couldn't find this in the course materials, so here is a general explanation.", self._usage)


class _RepairingAgent(_StreamingOnlyAgent):
    def __init__(self):
        super().__init__(["This is definitely covered by the course."], usage={"input_tokens": 2, "output_tokens": 3})
        self._client = _RepairingLLMClient({"input_tokens": 2, "output_tokens": 3})

    def build_system_prompt(self, _ctx):
        return "system"


class _FakeBlockDecisions:
    def to_dict(self):
        return {
            "operations": [],
            "cognitive_state": {"score": 0.12, "level": "low", "top_signals": []},
            "explanation": "No layout changes needed.",
        }


def _restore_real_provenance_module() -> None:
    """Ensure `services.provenance` points to the real module, not a test stub."""
    existing = sys.modules.get("services.provenance")
    if existing is not None and getattr(existing, "__file__", None):
        return

    provenance_path = Path(__file__).resolve().parents[1] / "apps/api/services/provenance.py"
    spec = importlib.util.spec_from_file_location("services.provenance", provenance_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["services.provenance"] = module


def _patch_submit_task(monkeypatch: pytest.MonkeyPatch, replacement) -> None:
    """Patch submit_task even when scheduler tests have stubbed modules."""
    module = sys.modules.get("services.activity.engine")
    if module is None:
        module = importlib.import_module("services.activity.engine")
    monkeypatch.setattr(module, "submit_task", replacement, raising=False)


@pytest.mark.asyncio
async def test_run_agent_turn_uses_stream_runtime_and_parses_actions(monkeypatch):
    dummy_agent = _StreamingOnlyAgent(
        [
            "Switched your workspace for exam prep. ",
            "[ACTION:apply_template:quick_reviewer]",
            "[ACTION:agent_insight:exam_prep:7-day countdown, 12 weak concepts]",
            "Let's keep practicing from here.",
        ],
        usage={"input_tokens": 5, "output_tokens": 7},
    )

    async def fake_prepare_agent_turn(ctx, _db, **_kwargs):
        return ctx, dummy_agent

    monkeypatch.setattr("services.agent.orchestrator.prepare_agent_turn", fake_prepare_agent_turn)

    ctx = await run_agent_turn(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="make quiz bigger",
        db=None,
        db_factory=None,
    )

    assert ctx.response == "Switched your workspace for exam prep. Let's keep practicing from here."
    assert ctx.actions == [
        {"action": "apply_template", "value": "quick_reviewer"},
        {"action": "agent_insight", "value": "exam_prep", "extra": "7-day countdown, 12 weak concepts"},
    ]
    assert ctx.total_tokens == 12


@pytest.mark.asyncio
async def test_run_agent_turn_does_not_double_count_function_calling_usage(monkeypatch):
    dummy_agent = _FunctionCallingAgent(
        ["Tool-backed answer."],
        usage={"input_tokens": 3, "output_tokens": 2},
    )

    async def fake_prepare_agent_turn(ctx, _db, **_kwargs):
        return ctx, dummy_agent

    monkeypatch.setattr("services.agent.orchestrator.prepare_agent_turn", fake_prepare_agent_turn)

    ctx = await run_agent_turn(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="help me solve this",
        db=None,
        db_factory=None,
    )

    assert ctx.response == "Tool-backed answer."
    assert ctx.input_tokens == 10
    assert ctx.output_tokens == 4
    assert ctx.total_tokens == 14


@pytest.mark.asyncio
async def test_vector_search_does_not_fall_back_to_conversation_memory(monkeypatch):
    class _Provider:
        async def embed(self, _query: str) -> list[float]:
            return [0.1, 0.2, 0.3]

    class _Result:
        class _Scalars:
            def all(self):
                return []

        def scalars(self):
            return self._Scalars()

    class _DB:
        async def execute(self, _query):
            return _Result()

    monkeypatch.setattr("services.embedding.registry.get_embedding_provider", lambda: _Provider())

    results = await vector_search(_DB(), uuid.uuid4(), "binary search", limit=3)

    assert results == []


def test_build_provenance_includes_explainable_scene_and_content_details():
    _restore_real_provenance_module()

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="help me prep for the exam",
        scene="exam_prep",
    )
    ctx.preferences = {"detail_level": "concise"}
    ctx.preference_sources = {"detail_level": "course"}
    ctx.content_docs = [{"title": "Week 6 Review", "source_type": "pdf", "content": "Key formulas and worked examples."}]
    ctx.metadata["scene_resolution"] = {"scene": "exam_prep", "mode": "inferred", "reason": "Matched study-mode cue 'exam'."}
    ctx.metadata["scene_switch"] = {"current_scene": "study_session", "target_scene": "exam_prep", "reason": "Detected exam prep intent."}

    provenance = build_provenance(ctx)

    assert provenance["scene"] == "exam_prep"
    assert provenance["scene_resolution"]["mode"] == "inferred"
    assert provenance["scene_switch"]["target_scene"] == "exam_prep"
    assert provenance["preference_details"][0]["source"] == "course"
    assert provenance["content_refs"][0]["title"] == "Week 6 Review"


def test_build_provenance_carries_evidence_summary_fields():
    _restore_real_provenance_module()

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="explain invariants and boundary updates",
        scene="study_session",
    )
    ctx.content_docs = [
        {
            "title": "Binary Search Invariants",
            "source_type": "pdf",
            "content": "Keep the target inside the bounds.",
            "evidence_summary": "Matches: invariants, boundary updates — Keep the target inside the bounds.",
            "matched_terms": ["invariants", "boundary"],
            "matched_facets": ["boundary updates"],
            "section_hit_count": 2,
        }
    ]

    provenance = build_provenance(ctx)

    assert provenance["content_refs"][0]["evidence_summary"].startswith("Matches:")
    assert provenance["content_refs"][0]["matched_terms"] == ["invariants", "boundary"]
    assert provenance["content_refs"][0]["section_hit_count"] == 2
    assert provenance["content_evidence_groups"][0]["label"] == "boundary updates"
    assert provenance["content_evidence_groups"][0]["section_count"] == 2


@pytest.mark.asyncio
async def test_run_agent_turn_records_verifier_and_repaired_response(monkeypatch):
    repairing_agent = _RepairingAgent()

    async def fake_prepare_agent_turn(ctx, _db, **_kwargs):
        ctx.intent = IntentType.LEARN
        ctx.content_docs = []
        return ctx, repairing_agent

    monkeypatch.setattr("services.agent.orchestrator.prepare_agent_turn", fake_prepare_agent_turn)

    ctx = await run_agent_turn(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="Explain radix sort",
        db=None,
        db_factory=None,
    )

    assert ctx.metadata["verifier"]["status"] == "repaired"
    assert "couldn't find this in the course materials" in ctx.response.lower()


@pytest.mark.asyncio
async def test_orchestrate_stream_complex_request_returns_task_link(monkeypatch):
    """Complex requests emit plan_step event with task_link AND continue with normal agent response."""
    async def fake_classify_intent(ctx):
        ctx.intent = IntentType.PLAN
        ctx.intent_confidence = 0.92
        return ctx

    async def fake_load_context(ctx, _db, db_factory=None):
        return ctx

    async def fake_create_plan(*_args, **_kwargs):
        return [
            {
                "step_index": 0,
                "step_type": "check_progress",
                "title": "Check progress",
                "agent": "assessment",
                "depends_on": [],
            }
        ]

    _task_id = uuid.uuid4()

    async def fake_submit_task(**_kwargs):
        return SimpleNamespace(id=_task_id, task_type="multi_step", status="queued")

    dummy_agent = _StreamingOnlyAgent(["Here is a quick answer to your question."])

    monkeypatch.setattr("services.agent.orchestrator.classify_intent", fake_classify_intent)
    monkeypatch.setattr("services.agent.orchestrator.load_context", fake_load_context)
    monkeypatch.setattr("services.agent.task_planner.is_complex_request", lambda _message: True)
    monkeypatch.setattr("services.agent.task_planner.create_plan", fake_create_plan)
    _patch_submit_task(monkeypatch, fake_submit_task)
    monkeypatch.setattr("services.agent.orchestrator.get_agent", lambda _intent: dummy_agent)

    events = []
    async for event in orchestrate_stream(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="Help me prepare for next week's exam with a full plan",
        db=None,
        db_factory=None,
    ):
        events.append(event)

    # plan_step event should be emitted with task link
    plan_events = [e for e in events if e["event"] == "plan_step"]
    assert len(plan_events) == 1
    plan_payload = json.loads(plan_events[0]["data"])
    assert plan_payload["task_id"] == str(_task_id)

    # Agent should still answer the question (not just return generic plan message)
    done_event = next(event for event in events if event["event"] == "done")
    payload = json.loads(done_event["data"])
    assert payload["task_link"]["task_type"] == "multi_step"


@pytest.mark.asyncio
async def test_prepare_agent_turn_and_orchestrate_stream_share_enrichment(monkeypatch):
    calls: list[str] = []

    async def fake_classify_intent(ctx):
        ctx.intent = IntentType.LEARN
        ctx.intent_confidence = 0.95
        return ctx

    async def fake_load_context(ctx, _db, db_factory=None):
        return ctx

    async def fake_enrichment(ctx, _db):
        calls.append("enrichment")
        ctx.metadata["block_decisions"] = _FakeBlockDecisions()
        return ctx

    dummy_agent = _StreamingOnlyAgent(["Shared enrichment path."])

    monkeypatch.setattr("services.agent.orchestrator.classify_intent", fake_classify_intent)
    monkeypatch.setattr("services.agent.orchestrator.load_context", fake_load_context)
    monkeypatch.setattr("services.agent.orchestrator._apply_turn_enrichment", fake_enrichment)
    monkeypatch.setattr("services.agent.orchestrator.get_agent", lambda _intent: dummy_agent)
    monkeypatch.setattr("services.agent.task_planner.is_complex_request", lambda _message: False)

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="help me",
    )
    await prepare_agent_turn(ctx, db=None, db_factory=None)

    async for _event in orchestrate_stream(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="Help me understand recursion",
        db=None,
        db_factory=None,
    ):
        pass

    assert calls == ["enrichment", "enrichment"]


@pytest.mark.asyncio
async def test_orchestrate_stream_emits_block_update_before_done(monkeypatch):
    async def fake_classify_intent(ctx):
        ctx.intent = IntentType.LEARN
        ctx.intent_confidence = 0.91
        return ctx

    async def fake_load_context(ctx, _db, db_factory=None):
        return ctx

    async def fake_enrichment(ctx, _db):
        ctx.metadata["block_decisions"] = _FakeBlockDecisions()
        return ctx

    dummy_agent = _StreamingOnlyAgent(["Answer with shared block updates."])

    monkeypatch.setattr("services.agent.orchestrator.classify_intent", fake_classify_intent)
    monkeypatch.setattr("services.agent.orchestrator.load_context", fake_load_context)
    monkeypatch.setattr("services.agent.orchestrator._apply_turn_enrichment", fake_enrichment)
    monkeypatch.setattr("services.agent.orchestrator.get_agent", lambda _intent: dummy_agent)
    monkeypatch.setattr("services.agent.task_planner.is_complex_request", lambda _message: True)
    monkeypatch.setattr("services.agent.task_planner.create_plan", AsyncMock(return_value=[
        {"step_index": 0, "step_type": "check_progress", "title": "Check progress", "agent": "assessment", "depends_on": []}
    ]))
    _patch_submit_task(
        monkeypatch,
        AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), task_type="multi_step", status="queued")),
    )

    events = []
    async for event in orchestrate_stream(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="make me a full preparation plan",
        db=None,
        db_factory=None,
    ):
        events.append(event)

    event_names = [event["event"] for event in events]
    assert "plan_step" in event_names
    assert "block_update" in event_names
    assert "done" in event_names
    assert event_names.index("plan_step") < event_names.index("done")
    assert event_names.index("block_update") < event_names.index("done")


@pytest.mark.asyncio
async def test_orchestrate_stream_emits_enrichment_warning_before_done(monkeypatch):
    async def fake_classify_intent(ctx):
        ctx.intent = IntentType.LEARN
        ctx.intent_confidence = 0.89
        return ctx

    async def fake_load_context(ctx, _db, db_factory=None):
        return ctx

    async def fake_enrichment(ctx, _db):
        ctx.metadata["stream_warnings"] = [
            {
                "type": "adaptation_degraded",
                "message": "Advanced adaptation is temporarily unavailable.",
            }
        ]
        return ctx

    dummy_agent = _StreamingOnlyAgent(["Answer continues without adaptive tuning."])

    monkeypatch.setattr("services.agent.orchestrator.classify_intent", fake_classify_intent)
    monkeypatch.setattr("services.agent.orchestrator.load_context", fake_load_context)
    monkeypatch.setattr("services.agent.orchestrator._apply_turn_enrichment", fake_enrichment)
    monkeypatch.setattr("services.agent.orchestrator.get_agent", lambda _intent: dummy_agent)
    monkeypatch.setattr("services.agent.task_planner.is_complex_request", lambda _message: False)

    events = []
    async for event in orchestrate_stream(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="Explain recursion",
        db=None,
        db_factory=None,
    ):
        events.append(event)

    event_names = [event["event"] for event in events]
    assert "warning" in event_names
    assert event_names.index("warning") < event_names.index("done")
    warning_payload = json.loads(next(event["data"] for event in events if event["event"] == "warning"))
    assert warning_payload["type"] == "adaptation_degraded"


@pytest.mark.asyncio
async def test_orchestrate_stream_enqueues_durable_post_process_task(monkeypatch):
    class _Agent(_StreamingOnlyAgent):
        def get_required_inputs(self):
            return []

        async def stream(self, ctx, _db):
            ctx.response += "Durable background work."
            yield "Durable background work."

    dummy_agent = _Agent(["Durable background work."], usage={"input_tokens": 8, "output_tokens": 5})
    submitted: dict[str, object] = {}

    async def fake_classify_intent(ctx):
        ctx.intent = IntentType.LEARN
        ctx.intent_confidence = 0.95
        return ctx

    async def fake_load_context(ctx, _db, db_factory=None):
        return ctx

    async def fake_apply_verifier(ctx, _agent):
        return ctx

    async def fake_apply_reflection(ctx):
        return ctx

    async def fake_submit_task(**kwargs):
        submitted.update(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), task_type=kwargs["task_type"], status="queued")

    monkeypatch.setattr("services.agent.orchestrator.classify_intent", fake_classify_intent)
    monkeypatch.setattr("services.agent.orchestrator.load_context", fake_load_context)
    monkeypatch.setattr("services.agent.orchestrator.get_agent", lambda _intent: dummy_agent)
    monkeypatch.setattr("services.agent.orchestrator.apply_verifier", fake_apply_verifier)
    monkeypatch.setattr("services.agent.orchestrator.apply_reflection", fake_apply_reflection)
    monkeypatch.setattr("services.agent.task_planner.is_complex_request", lambda _message: False)
    _patch_submit_task(monkeypatch, fake_submit_task)

    events = []
    async for event in orchestrate_stream(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="Explain quicksort",
        db=None,
        db_factory=None,
    ):
        events.append(event)

    done_event = next(event for event in events if event["event"] == "done")
    payload = json.loads(done_event["data"])
    assert payload["agent"] == "dummy"
    assert submitted["task_type"] == "chat_post_process"
    assert submitted["source"] == "agent"
    assert submitted["max_attempts"] == 3
    assert submitted["input_json"]["context"]["response"] == "Durable background work."


@pytest.mark.asyncio
async def test_orchestrate_stream_guided_session_parses_action_markers(monkeypatch):
    task_id = str(uuid.uuid4())

    class _GuidedAgent(_StreamingOnlyAgent):
        async def stream(self, _ctx, _db):
            yield "Let's jump in. [ACTION:focus_topic:node-42]"

    guided_agent = _GuidedAgent([""], usage={"input_tokens": 1, "output_tokens": 1})

    async def fake_get_session_state(_db, _user_id, _task_id):
        return {
            "current_phase": "teach",
            "topic": {"title": "Binary Search"},
            "completed_phases": [],
        }

    async def fake_advance_phase(_db, _user_id, _task_id):
        return {
            "current_phase": "practice",
            "completed_phases": ["teach"],
        }

    async def fake_load_context(ctx, _db):
        return ctx

    monkeypatch.setattr("services.agent.orchestrator.get_agent", lambda _intent: guided_agent)
    monkeypatch.setattr("services.agent.orchestrator.load_context", fake_load_context)
    monkeypatch.setattr("services.agent.guided_session_handler.get_agent", lambda _intent: guided_agent)
    monkeypatch.setattr("services.agent.guided_session_handler.load_context", fake_load_context)
    monkeypatch.setattr("services.agent.guided_session.get_session_state", fake_get_session_state)
    monkeypatch.setattr("services.agent.guided_session.advance_phase", fake_advance_phase)
    monkeypatch.setattr("services.agent.guided_session.build_phase_prompt", lambda *_args, **_kwargs: "Teach this")

    events = []
    async for event in orchestrate_stream(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message=f"[GUIDED_SESSION:start:{task_id}]",
        db=None,
        db_factory=None,
    ):
        events.append(event)

    action_events = [event for event in events if event["event"] == "action"]
    assert action_events
    payloads = [json.loads(event["data"]) for event in action_events]
    assert {"action": "focus_topic", "value": "node-42"} in payloads
