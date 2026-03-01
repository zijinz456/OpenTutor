import uuid

import pytest

from services.agent.scene_agent import SceneAgent
from services.agent.state import AgentContext
from services.agent.orchestrator import _build_provenance
from services.agent.orchestrator import run_agent_turn
from services.search.hybrid import vector_search


class _DummyLLMClient:
    def __init__(self, usage: dict[str, int], supports_tools: bool = False):
        self._usage = usage
        if supports_tools:
            self.chat_with_tools = self._chat_with_tools

    def get_last_usage(self) -> dict[str, int]:
        return self._usage

    async def _chat_with_tools(self, *_args, **_kwargs):
        raise NotImplementedError


class _StreamingOnlyAgent:
    name = "dummy"

    def __init__(self, chunks: list[str], usage: dict[str, int] | None = None):
        self._chunks = chunks
        self._client = _DummyLLMClient(usage or {"input_tokens": 0, "output_tokens": 0})

    def get_llm_client(self):
        return self._client

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


@pytest.mark.asyncio
async def test_run_agent_turn_uses_stream_runtime_and_parses_actions(monkeypatch):
    dummy_agent = _StreamingOnlyAgent(
        [
            "Switched your workspace. ",
            "[ACTION:set_layout_preset:quizFocused]",
            "Let's keep practicing from here.",
        ],
        usage={"input_tokens": 5, "output_tokens": 7},
    )

    async def fake_prepare_agent_turn(ctx, _db):
        return ctx, dummy_agent

    monkeypatch.setattr("services.agent.orchestrator.prepare_agent_turn", fake_prepare_agent_turn)

    ctx = await run_agent_turn(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        message="make quiz bigger",
        db=None,
        db_factory=None,
    )

    assert ctx.response == "Switched your workspace. Let's keep practicing from here."
    assert ctx.actions == [{"action": "set_layout_preset", "value": "quizFocused"}]
    assert ctx.total_tokens == 12


@pytest.mark.asyncio
async def test_run_agent_turn_does_not_double_count_function_calling_usage(monkeypatch):
    dummy_agent = _FunctionCallingAgent(
        ["Tool-backed answer."],
        usage={"input_tokens": 3, "output_tokens": 2},
    )

    async def fake_prepare_agent_turn(ctx, _db):
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
async def test_scene_agent_falls_back_to_teaching_when_no_scene_switch(monkeypatch):
    async def fake_teaching_stream(self, ctx, _db):
        ctx.response = "Detailed help from teaching agent."
        yield ctx.response

    monkeypatch.setattr("services.agent.teaching.TeachingAgent.stream", fake_teaching_stream)

    agent = SceneAgent()
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="Can you explain eigenvalues again?",
        scene="study_session",
    )

    chunks = []
    async for chunk in agent.stream(ctx, None):
        chunks.append(chunk)

    assert "".join(chunks) == "Detailed help from teaching agent."
    assert ctx.response == "Detailed help from teaching agent."


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

    provenance = _build_provenance(ctx)

    assert provenance["scene"] == "exam_prep"
    assert provenance["scene_resolution"]["mode"] == "inferred"
    assert provenance["scene_switch"]["target_scene"] == "exam_prep"
    assert provenance["preference_details"][0]["source"] == "course"
    assert provenance["content_refs"][0]["title"] == "Week 6 Review"
