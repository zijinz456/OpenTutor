"""Unit tests for :class:`services.agent.agents.tutor.TutorAgent` Phase 7 guardrails.

Covers T2 scope from ``plan/guardrails_phase7.md``:

- ``build_system_prompt`` appends the strict-mode directive only when
  ``ctx.metadata["guardrails_strict"] is True`` (T1-provided flag).
- ``execute`` bypasses the LLM entirely when T3 middleware sets
  ``ctx.metadata["skip_tutor_llm"]`` — the agent writes ``REFUSAL_TEMPLATE``
  to ``ctx.response`` and returns without calling ``client.chat``.
- ``stream`` honors the same bypass: yields exactly one chunk with the
  refusal template and never constructs / calls the LLM client.

All tests stub the LLM via ``monkeypatch`` on ``get_llm_client`` — no
network calls. The DB argument is stubbed with ``MagicMock`` since the
bypass path exits before any DB access.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from services.agent.agents.prompts import GUARDRAILS_STRICT_DIRECTIVE, REFUSAL_TEMPLATE
from services.agent.agents.tutor import TutorAgent
from services.agent.state import AgentContext


# ── helpers ────────────────────────────────────────────────────────


def _make_ctx(**metadata: Any) -> AgentContext:
    """Minimal AgentContext — identity fields plus an optional metadata dict."""
    return AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
        user_message="What is a transformer?",
        metadata=dict(metadata),
    )


def _install_tracking_llm(
    monkeypatch: pytest.MonkeyPatch,
    agent: TutorAgent,
) -> MagicMock:
    """Replace ``agent.get_llm_client`` with a MagicMock whose ``.chat``
    and ``.stream_chat`` are tracked. Returns the client mock so tests
    can assert ``client.chat.call_count == 0``.

    Any accidental LLM call raises ``AssertionError`` — the bypass path
    MUST NOT reach the LLM.
    """
    client = MagicMock()

    async def _boom_chat(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("LLM chat() called — bypass path failed")

    async def _boom_stream(*_args: Any, **_kwargs: Any):
        raise AssertionError("LLM stream_chat() called — bypass path failed")
        yield  # pragma: no cover — make this an async generator

    # MagicMock auto-creates attributes; we replace .chat / .stream_chat
    # with real async callables so `await client.chat(...)` would actually
    # hit the assertion rather than returning a coroutine-wrapped mock.
    client.chat = MagicMock(side_effect=_boom_chat)
    client.stream_chat = MagicMock(side_effect=_boom_stream)

    monkeypatch.setattr(agent, "get_llm_client", lambda _ctx=None: client)
    return client


# ── 1. build_system_prompt — strict directive appended ────────────


def test_build_system_prompt_appends_directive_when_strict() -> None:
    """``guardrails_strict=True`` in metadata → prompt contains the directive."""
    agent = TutorAgent()
    ctx = _make_ctx(guardrails_strict=True)

    prompt = agent.build_system_prompt(ctx)

    assert "STRICT GROUNDING MODE" in prompt
    assert "1-based indices" in prompt
    # Sanity — the full directive string is present verbatim.
    assert GUARDRAILS_STRICT_DIRECTIVE.strip() in prompt


# ── 2. build_system_prompt — flag absent → no directive ───────────


def test_build_system_prompt_omits_directive_when_flag_absent() -> None:
    """No ``guardrails_strict`` in metadata → directive NOT in prompt."""
    agent = TutorAgent()
    ctx = _make_ctx()  # empty metadata

    prompt = agent.build_system_prompt(ctx)

    assert "STRICT GROUNDING MODE" not in prompt


def test_build_system_prompt_omits_directive_when_flag_false() -> None:
    """``guardrails_strict=False`` → directive still NOT in prompt.

    The check is ``is True``, so truthy-but-not-True values (e.g. a string
    "true" from a misbehaving client) must also be rejected. This guards
    against accidental opt-in on bad input.
    """
    agent = TutorAgent()
    ctx = _make_ctx(guardrails_strict=False)

    prompt = agent.build_system_prompt(ctx)

    assert "STRICT GROUNDING MODE" not in prompt


# ── 3. execute — bypass path skips the LLM ────────────────────────


@pytest.mark.asyncio
async def test_execute_skips_llm_when_skip_tutor_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``skip_tutor_llm`` set → ``ctx.response = REFUSAL_TEMPLATE``, 0 LLM calls."""
    agent = TutorAgent()
    client = _install_tracking_llm(monkeypatch, agent)
    ctx = _make_ctx(skip_tutor_llm=True)
    db = MagicMock()  # bypass path never touches the session

    returned = await agent.execute(ctx, db)

    assert returned is ctx
    assert ctx.response == REFUSAL_TEMPLATE
    assert client.chat.call_count == 0
    assert client.stream_chat.call_count == 0


# ── 4. stream — bypass path yields refusal, no LLM ────────────────


@pytest.mark.asyncio
async def test_stream_skips_llm_when_skip_tutor_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``skip_tutor_llm`` set → stream yields only REFUSAL_TEMPLATE, 0 LLM calls."""
    agent = TutorAgent()
    client = _install_tracking_llm(monkeypatch, agent)
    ctx = _make_ctx(skip_tutor_llm=True)
    db = MagicMock()

    chunks: list[str] = []
    async for chunk in agent.stream(ctx, db):
        chunks.append(chunk)

    assert chunks == [REFUSAL_TEMPLATE]
    assert ctx.response == REFUSAL_TEMPLATE
    assert client.chat.call_count == 0
    assert client.stream_chat.call_count == 0
