"""Unit tests for the chat orchestrator's routing and per-turn enrichment (issue #33).

Covers intent classification → agent routing, fatigue detection, cognitive
load enrichment (mocked), graceful degradation, and the clarify-input parser.
All external dependencies (LLM, database) are mocked.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from services.agent.fatigue import detect_fatigue
from services.agent.orchestrator import (
    _ADAPTATION_WARNING,
    _apply_turn_enrichment,
    _parse_clarify_inputs,
    _record_stream_warning,
)
from services.agent.registry import INTENT_AGENT_MAP, get_agent
from services.agent.router import classify_intent, rule_match
from services.agent.state import AgentContext, IntentType


def _ctx(message: str) -> AgentContext:
    return AgentContext(
        user_id=uuid.uuid4(), course_id=uuid.uuid4(), user_message=message,
    )


# ── Intent classification → agent routing ──


@pytest.mark.asyncio
@pytest.mark.parametrize("message,intent,agent_name", [
    ("Can you explain photosynthesis to me?", IntentType.LEARN, "tutor"),
    ("quiz me on chapter 3", IntentType.LEARN, "tutor"),
    ("create a study schedule for finals", IntentType.PLAN, "planner"),
    ("maximize the flashcard block", IntentType.LAYOUT, "layout"),
])
async def test_intent_routes_to_correct_agent(message, intent, agent_name):
    ctx = await classify_intent(_ctx(message))
    assert ctx.intent == intent
    assert ctx.intent_confidence >= 0.8
    assert INTENT_AGENT_MAP[ctx.intent] == agent_name
    assert get_agent(ctx.intent) is get_agent(intent)


@pytest.mark.asyncio
async def test_unknown_intent_falls_back_to_general():
    ctx = await classify_intent(_ctx("good morning!"))
    assert ctx.intent == IntentType.GENERAL
    assert ctx.intent_confidence == 0.5
    # GENERAL routes to the tutor agent rather than failing
    assert INTENT_AGENT_MAP[IntentType.GENERAL] == "tutor"
    assert get_agent(IntentType.GENERAL) is not None


def test_rule_match_returns_none_for_chitchat():
    assert rule_match("thanks, that was great") is None


# ── Fatigue detection ──


def test_fatigue_high_for_frustrated_message():
    frustrated = detect_fatigue("I give up, this is impossible, I'm so tired of this")
    calm = detect_fatigue("Could you explain the chain rule?")
    assert frustrated > calm
    assert 0.0 <= calm <= 1.0 and 0.0 <= frustrated <= 1.0


@pytest.mark.asyncio
async def test_enrichment_attaches_fatigue_score():
    ctx = _ctx("I give up, this is impossible")
    with patch(
        "services.cognitive_load.compute_cognitive_load",
        AsyncMock(return_value={"load": 0.4, "level": "medium", "consecutive_high": 0}),
    ):
        enriched = await _apply_turn_enrichment(ctx, db=AsyncMock())
    assert 0.0 <= enriched.metadata["fatigue_score"] <= 1.0
    assert enriched.metadata["fatigue_score"] > 0.0


# ── Cognitive load enrichment ──


@pytest.mark.asyncio
async def test_enrichment_attaches_cognitive_load():
    ctx = _ctx("explain derivatives")
    payload = {"load": 0.72, "level": "high", "consecutive_high": 0, "signals": {}}
    compute = AsyncMock(return_value=payload)
    decisions = {"add": [], "remove": []}
    with patch("services.cognitive_load.compute_cognitive_load", compute), \
         patch("services.agent.signals.collect_signals", AsyncMock(return_value=[])), \
         patch("services.block_decision.preference.compute_block_preferences", AsyncMock(return_value=None)), \
         patch("services.block_decision.engine.compute_block_decisions", AsyncMock(return_value=decisions)):
        enriched = await _apply_turn_enrichment(ctx, db=AsyncMock())

    compute.assert_awaited_once()
    assert enriched.metadata["cognitive_load"] == payload
    assert 0.0 <= enriched.metadata["cognitive_load"]["load"] <= 1.0
    assert enriched.metadata["block_decisions"] == decisions
    # No degradation warning on the fully-healthy path
    assert enriched.metadata.get("stream_warnings", []) == []


@pytest.mark.asyncio
async def test_enrichment_degrades_gracefully_without_db():
    ctx = _ctx("explain derivatives")
    enriched = await _apply_turn_enrichment(ctx, db=None)
    # Fatigue still computed; cognitive load skipped with a user-visible warning
    assert "fatigue_score" in enriched.metadata
    assert "cognitive_load" not in enriched.metadata
    warnings = enriched.metadata["stream_warnings"]
    assert any(w["type"] == "adaptation_degraded" for w in warnings)


@pytest.mark.asyncio
async def test_enrichment_degrades_when_cognitive_load_crashes():
    ctx = _ctx("explain derivatives")
    with patch(
        "services.cognitive_load.compute_cognitive_load",
        AsyncMock(side_effect=ValueError("boom")),
    ):
        enriched = await _apply_turn_enrichment(ctx, db=AsyncMock())
    assert any(
        w["type"] == "adaptation_degraded" for w in enriched.metadata["stream_warnings"]
    )


# ── Stream warning dedup ──


def test_stream_warning_deduplicates():
    ctx = _ctx("x")
    _record_stream_warning(ctx, _ADAPTATION_WARNING)
    _record_stream_warning(ctx, _ADAPTATION_WARNING)
    assert len(ctx.metadata["stream_warnings"]) == 1


# ── Clarify input parsing ──


def test_parse_clarify_json_format():
    assert _parse_clarify_inputs('{"type": "clarify", "key": "topic", "value": "calculus"}') == {
        "topic": "calculus"
    }


def test_parse_clarify_legacy_format():
    assert _parse_clarify_inputs("[CLARIFY:depth:beginner]") == {"depth": "beginner"}


def test_parse_clarify_rejects_plain_text():
    assert _parse_clarify_inputs("just a normal chat message") == {}
    assert _parse_clarify_inputs('{"type": "other", "key": "k", "value": "v"}') == {}
