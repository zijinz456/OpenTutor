"""Regression tests for the core learning-loop fixes.

Covers:
- conversation history reaching the LLM (normalize_history + react loop)
- chat post-processing running inline when the activity engine is off
- extract_questions callers unpacking QuizExtractionOutcome
- tolerant objective grading + LLM fallback for free text
- mastery no longer depends on (never recorded) study time
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.llm.base_client import build_chat_messages, normalize_history
from services.practice.grading import grade_answer, grade_objective, normalize_text


# ── normalize_history ──


def test_normalize_history_drops_current_message_and_alternates():
    history = [
        {"role": "assistant", "content": "stray opener"},
        {"role": "user", "content": "what is BKT?"},
        {"role": "user", "content": "(follow-up)"},
        {"role": "assistant", "content": "Bayesian Knowledge Tracing..."},
        {"role": "system", "content": "ignored"},
        {"role": "user", "content": "   "},
        {"role": "user", "content": "and FSRS?"},
    ]
    out = normalize_history(history, "and FSRS?")
    assert out == [
        {"role": "user", "content": "what is BKT?\n\n(follow-up)"},
        {"role": "assistant", "content": "Bayesian Knowledge Tracing..."},
    ]


def test_normalize_history_keeps_dangling_user_turn_that_is_not_current():
    out = normalize_history([{"role": "user", "content": "earlier unanswered"}], "now")
    assert out == [{"role": "user", "content": "earlier unanswered"}]


def test_build_chat_messages_orders_system_history_user():
    msgs = build_chat_messages("sys", "now", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[-1]["content"] == "now"


# ── react loop passes history to the client ──


class _RecordingClient:
    def __init__(self):
        self.calls: list[dict] = []

    async def stream_chat(self, system_prompt, user_message, images=None, history=None):
        self.calls.append({"system": system_prompt, "user": user_message, "history": history})
        yield "ok"


@pytest.mark.asyncio
async def test_react_stream_without_tools_passes_history():
    from services.agent.state import AgentContext
    from services.agent.tools.react_loop import react_stream

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="and FSRS?",
        conversation_history=[
            {"role": "user", "content": "what is BKT?"},
            {"role": "assistant", "content": "BKT is..."},
            {"role": "user", "content": "and FSRS?"},
        ],
    )
    client = _RecordingClient()
    events = [e async for e in react_stream(client, "sys", ctx.user_message, ctx, db=None, tool_names=[])]

    assert events[-1]["type"] == "answer_done"
    assert client.calls[0]["history"] == [
        {"role": "user", "content": "what is BKT?"},
        {"role": "assistant", "content": "BKT is..."},
    ]
    assert client.calls[0]["user"] == "and FSRS?"


@pytest.mark.asyncio
async def test_function_calling_messages_include_history():
    from services.agent.state import AgentContext
    from services.agent.tools import react_loop

    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="now",
        conversation_history=[{"role": "user", "content": "before"}, {"role": "assistant", "content": "reply"}],
    )
    seen: dict = {}

    class _ToolClient:
        async def chat_with_tools(self, messages, tools):
            seen["messages"] = list(messages)
            return "final", [], {"input_tokens": 1, "output_tokens": 1}

        async def stream_chat(self, *a, **k):  # pragma: no cover - not reached
            yield ""

    fake_tool = SimpleNamespace(name="noop", to_openai_schema=lambda: {"type": "function", "function": {"name": "noop"}})
    fake_registry = SimpleNamespace(get_tools=lambda names: [fake_tool], get=lambda n: None, execute=AsyncMock())
    with patch.object(react_loop, "get_tool_registry", return_value=fake_registry):
        events = [e async for e in react_loop.react_stream(_ToolClient(), "sys", "now", ctx, db=None, tool_names=["noop"])]

    assert [m["role"] for m in seen["messages"]] == ["system", "user", "assistant", "user"]
    assert seen["messages"][-1]["content"] == "now"
    assert events[-1]["type"] == "answer_done"


# ── post-processing runs inline when the activity engine is off ──


def test_orchestrator_runs_post_process_inline_by_default():
    import inspect

    from services.agent import orchestrator

    src = inspect.getsource(orchestrator.orchestrate_stream)
    assert "settings.app_run_activity_engine" in src
    assert "run_post_process_bundle(bg_ctx, db_factory)" in src


# ── extract_questions callers ──


@pytest.mark.asyncio
async def test_quiz_tool_unpacks_extraction_outcome():
    from services.parser.quiz import QuizExtractionOutcome

    src = __import__("inspect").getsource(__import__("services.agent.tools.quiz_tools", fromlist=["x"]))
    assert "outcome = await extract_questions(" in src and "outcome.problems" in src
    src = __import__("inspect").getsource(__import__("services.activity.engine_dispatch", fromlist=["x"]))
    assert "outcome.problems[:count]" in src
    src = __import__("inspect").getsource(__import__("services.ingestion.auto_generation.practice", fromlist=["x"]))
    assert "problems.extend(outcome.problems)" in src
    assert isinstance(QuizExtractionOutcome().problems, list)


def test_dispatch_no_longer_spawns_second_generator():
    import inspect

    from services.ingestion import dispatch

    assert "_safe_auto_generate" not in inspect.getsource(dispatch)


# ── grading ──


def _problem(qtype, correct, options=None, metadata=None):
    return SimpleNamespace(
        question_type=qtype, question="Q?", correct_answer=correct, options=options, problem_metadata=metadata
    )


def test_normalize_text_strips_case_punctuation_and_width():
    assert normalize_text("  Dijkstra's!  ") == "dijkstras"
    assert normalize_text("Ｐaris.") == "paris"


@pytest.mark.parametrize(
    "qtype,correct,options,answer,expected",
    [
        ("mc", "B", {"A": "Lisbon", "B": "Paris", "C": "Rome", "D": "Oslo"}, "b", True),
        ("mc", "B", {"A": "Lisbon", "B": "Paris", "C": "Rome", "D": "Oslo"}, "Paris", True),
        ("mc", "B", {"A": "Lisbon", "B": "Paris", "C": "Rome", "D": "Oslo"}, "B. Paris", True),
        ("mc", "B", {"A": "Lisbon", "B": "Paris", "C": "Rome", "D": "Oslo"}, "Rome", False),
        ("tf", "True", None, "yes", True),
        ("tf", "False", None, "错", True),
        ("tf", "True", None, "false", False),
        ("select_all", "A, C", {"A": "1", "B": "2", "C": "3", "D": "4"}, "c,a", True),
        ("select_all", "A, C", {"A": "1", "B": "2", "C": "3", "D": "4"}, "A", False),
        ("fill_blank", "3.14", None, "3.140", True),
        ("fill_blank", "50%", None, "0.5", True),
        ("fill_blank", "Dijkstra's", None, "dijkstras", True),
    ],
)
def test_grade_objective(qtype, correct, options, answer, expected):
    assert grade_objective(_problem(qtype, correct, options), answer) is expected


def test_grade_objective_uses_accepted_answers():
    p = _problem("fill_blank", "Dijkstra's", metadata={"accepted_answers": ["Dijkstra", "Dijkstra's algorithm"]})
    assert grade_objective(p, "dijkstra algorithm's".replace(" algorithm's", "")) is True
    assert grade_objective(p, "Bellman-Ford") is None  # needs semantic grading


@pytest.mark.asyncio
async def test_grade_answer_falls_back_to_llm_for_paraphrase():
    p = _problem("short_answer", "Paris is the capital of France")
    fake = AsyncMock()
    fake.chat.return_value = ('{"is_correct": true, "rationale": "Same meaning."}', {})
    with patch("services.llm.router.get_llm_client", return_value=fake):
        result = await grade_answer(p, "The French capital is Paris")
    assert result.is_correct is True
    assert result.mode == "llm"
    assert result.rationale == "Same meaning."


@pytest.mark.asyncio
async def test_grade_answer_llm_failure_is_reported_not_raised():
    p = _problem("short_answer", "Paris")
    fake = AsyncMock()
    fake.chat.side_effect = ConnectionError("down")
    with patch("services.llm.router.get_llm_client", return_value=fake):
        result = await grade_answer(p, "somewhere in France")
    assert result.is_correct is False
    assert result.mode == "unavailable"
    assert "text_grading_unavailable" in result.warnings


@pytest.mark.asyncio
async def test_grade_answer_objective_never_calls_llm():
    p = _problem("mc", "A", {"A": "x", "B": "y", "C": "z", "D": "w"})
    with patch("services.llm.router.get_llm_client") as get_client:
        result = await grade_answer(p, "x")
    assert result.is_correct and result.mode == "objective"
    get_client.assert_not_called()


# ── mastery has no study-time term ──


def test_mastery_formula_has_no_time_term():
    import inspect

    from services.progress import tracker

    src = inspect.getsource(tracker.update_quiz_result)
    assert "time_spent_minutes / 60" not in src
    assert "bkt_mastery * 0.7 + weighted_mastery * 0.3" in src
