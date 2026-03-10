"""Tests for services.agent.stream_events — StreamEvent formatting."""

import json
import warnings

import pytest

warnings.filterwarnings(
    "ignore",
    message="services\\.agent\\.stream_events is deprecated and kept for compatibility only\\.",
    category=DeprecationWarning,
)

from services.agent.stream_events import StreamEvent


# ── Factory methods ──


def test_content_factory():
    e = StreamEvent.content("Hello world")
    assert e.type == "content"
    assert e.data["content"] == "Hello world"


def test_thought_factory():
    e = StreamEvent.thought("thinking...")
    assert e.type == "thought"
    assert e.data["content"] == "thinking..."


def test_tool_start_factory_with_explanation():
    e = StreamEvent.tool_start("search", input_data="query", explanation="Looking up notes")
    assert e.type == "tool_start"
    assert e.data["tool"] == "search"
    assert e.data["input"] == "query"
    assert e.data["explanation"] == "Looking up notes"


def test_tool_start_factory_without_explanation():
    e = StreamEvent.tool_start("search")
    assert "explanation" not in e.data


def test_tool_result_factory():
    e = StreamEvent.tool_result("search", result="found 3 items", explanation="Done")
    assert e.data["tool"] == "search"
    assert e.data["result"] == "found 3 items"
    assert e.data["explanation"] == "Done"


def test_action_factory():
    e = StreamEvent.action("navigate", url="/page")
    assert e.type == "action"
    assert e.data["type"] == "navigate"
    assert e.data["url"] == "/page"


def test_status_factory():
    e = StreamEvent.status("thinking", step=2)
    assert e.data["phase"] == "thinking"
    assert e.data["step"] == 2


def test_done_factory():
    e = StreamEvent.done(total_tokens=500)
    assert e.type == "done"
    assert e.data["total_tokens"] == 500


def test_error_factory():
    e = StreamEvent.error("something broke")
    assert e.type == "error"
    assert e.data["message"] == "something broke"


# ── to_sse ──


def test_content_to_sse():
    e = StreamEvent.content("hi")
    sse = e.to_sse()
    assert sse["event"] == "message"
    payload = json.loads(sse["data"])
    assert payload["content"] == "hi"


def test_tool_start_to_sse():
    e = StreamEvent.tool_start("fetch", explanation="Fetching data")
    sse = e.to_sse()
    assert sse["event"] == "tool_status"
    payload = json.loads(sse["data"])
    assert payload["status"] == "running"
    assert payload["tool"] == "fetch"
    assert payload["explanation"] == "Fetching data"


def test_tool_result_to_sse():
    e = StreamEvent.tool_result("fetch")
    sse = e.to_sse()
    payload = json.loads(sse["data"])
    assert payload["status"] == "complete"


def test_action_to_sse():
    e = StreamEvent.action("open_block", block_id="abc")
    sse = e.to_sse()
    assert sse["event"] == "action"
    payload = json.loads(sse["data"])
    assert payload["block_id"] == "abc"


def test_done_to_sse():
    e = StreamEvent.done()
    sse = e.to_sse()
    assert sse["event"] == "done"


def test_error_to_sse():
    e = StreamEvent.error("fail")
    sse = e.to_sse()
    assert sse["event"] == "error"
    payload = json.loads(sse["data"])
    assert payload["message"] == "fail"


# ── to_dict (legacy) ──


def test_to_dict_merges_type_and_data():
    e = StreamEvent.content("x")
    d = e.to_dict()
    assert d["type"] == "content"
    assert d["content"] == "x"
