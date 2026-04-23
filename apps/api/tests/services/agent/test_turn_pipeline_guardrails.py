"""Tests for Phase 7 Guardrails T3 — ``turn_pipeline`` middleware.

Covers the retrieval-threshold pre-gate and the structured-output
post-parse. Both helpers are pure functions on ``AgentContext`` metadata,
so the tests drive them synchronously without spinning up agents / DBs.

See ``plan/guardrails_phase7.md`` for the contract being verified.
"""

from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

from services.agent.state import AgentContext
from services.agent.turn_pipeline import _apply_guardrails_post, _apply_guardrails_pre


# ── helpers ────────────────────────────────────────────────────────


def _make_ctx() -> AgentContext:
    """Minimal context — identity fields only; metadata starts empty."""
    return AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="",
    )


def _settings(min_score: float = 0.62) -> SimpleNamespace:
    """Stand-in for the global ``Settings`` — only the field we read."""
    return SimpleNamespace(guardrails_retrieval_min_score=min_score)


# ── pre-gate ───────────────────────────────────────────────────────


def test_pre_gate_no_retrieval_sets_skip_and_refusal() -> None:
    """Empty ``content_docs`` under strict mode → refusal path armed."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = True
    ctx.content_docs = []

    _apply_guardrails_pre(ctx, _settings())

    assert ctx.metadata["skip_tutor_llm"] is True
    assert ctx.metadata["guardrails_refusal_reason"] == "no_retrieval"
    assert ctx.metadata["guardrails_top_score"] == 0.0


def test_pre_gate_low_score_below_threshold_sets_skip() -> None:
    """Top score below ``guardrails_retrieval_min_score`` → refusal."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = True
    ctx.content_docs = [{"score": 0.5, "id": "a"}]

    _apply_guardrails_pre(ctx, _settings(min_score=0.62))

    assert ctx.metadata["skip_tutor_llm"] is True
    assert ctx.metadata["guardrails_refusal_reason"] == "no_retrieval"
    assert ctx.metadata["guardrails_top_score"] == 0.5


def test_pre_gate_above_threshold_does_not_skip() -> None:
    """Top score ≥ threshold → LLM proceeds; only score recorded."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = True
    ctx.content_docs = [{"score": 0.8, "id": "a"}, {"score": 0.4, "id": "b"}]

    _apply_guardrails_pre(ctx, _settings(min_score=0.62))

    assert ctx.metadata.get("skip_tutor_llm") is not True
    assert ctx.metadata["guardrails_top_score"] == 0.8
    assert "guardrails_refusal_reason" not in ctx.metadata


def test_pre_gate_respects_strict_false() -> None:
    """Non-strict turn is a no-op — no metadata mutations at all."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = False
    ctx.content_docs = [{"score": 0.1}]

    _apply_guardrails_pre(ctx, _settings())

    assert "skip_tutor_llm" not in ctx.metadata
    assert "guardrails_top_score" not in ctx.metadata
    assert "guardrails_refusal_reason" not in ctx.metadata


# ── post-parse ─────────────────────────────────────────────────────


def test_post_parse_success_populates_metadata() -> None:
    """Valid structured response → parsed into metadata + clean response."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = True
    ctx.metadata["guardrails_top_score"] = 0.8
    ctx.content_docs = [
        {"id": "d1", "source_file": "a.pdf", "text": "alpha text"},
        {"id": "d2", "source_file": "b.pdf", "text": "beta text"},
        {"id": "d3", "source_file": "c.pdf", "text": "gamma text"},
    ]
    ctx.response = '{"answer":"test","confidence":4,"citations":[1,3]}'

    _apply_guardrails_post(ctx)

    g = ctx.metadata["guardrails"]
    assert g["answer"] == "test"
    assert g["confidence"] == 4
    assert g["citations"] == [1, 3]
    assert len(g["citation_chunks"]) == 2
    assert g["citation_chunks"][0]["id"] == "d1"
    assert g["citation_chunks"][0]["source_file"] == "a.pdf"
    assert g["citation_chunks"][1]["id"] == "d3"
    assert g["strict_mode"] is True
    assert g["top_retrieval_score"] == 0.8
    assert ctx.response == "test"


def test_post_parse_invalid_citation_indices_stripped() -> None:
    """Out-of-range citations are dropped; in-range ones survive."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = True
    ctx.content_docs = [
        {"id": "d1", "source_file": "a.pdf", "text": "x"},
        {"id": "d2", "source_file": "b.pdf", "text": "y"},
        {"id": "d3", "source_file": "c.pdf", "text": "z"},
    ]
    ctx.response = '{"answer":"x","confidence":3,"citations":[1,99,200]}'

    _apply_guardrails_post(ctx)

    g = ctx.metadata["guardrails"]
    assert g["citations"] == [1]
    assert len(g["citation_chunks"]) == 1
    assert g["citation_chunks"][0]["id"] == "d1"


def test_post_parse_malformed_json_fallback(
    caplog: logging.LogRecord,
) -> None:
    """Unparseable response → ``parse_fallback`` with raw text preserved."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = True
    ctx.response = "not json at all"

    with caplog.at_level(logging.WARNING, logger="services.agent.turn_pipeline"):
        _apply_guardrails_post(ctx)

    g = ctx.metadata["guardrails"]
    assert g["refusal_reason"] == "parse_fallback"
    assert g["answer"] == "not json at all"
    assert g["citations"] == []
    # logger.warning emitted with the documented message.
    assert any(
        "guardrails_parse_fallback" in record.message for record in caplog.records
    )


def test_post_skip_flag_short_circuits_to_refusal() -> None:
    """Pre-gate refusal propagates; no JSON parse attempted."""
    ctx = _make_ctx()
    ctx.metadata["guardrails_strict"] = True
    ctx.metadata["skip_tutor_llm"] = True
    ctx.metadata["guardrails_refusal_reason"] = "no_retrieval"
    ctx.metadata["guardrails_top_score"] = 0.1
    # A garbage response that would otherwise trigger parse_fallback.
    ctx.response = "totally not json"

    _apply_guardrails_post(ctx)

    g = ctx.metadata["guardrails"]
    assert g["refusal_reason"] == "no_retrieval"
    assert g["answer"] is None
    assert g["top_retrieval_score"] == 0.1
    # Response untouched (tutor agent is expected to produce the canned refusal).
    assert ctx.response == "totally not json"
