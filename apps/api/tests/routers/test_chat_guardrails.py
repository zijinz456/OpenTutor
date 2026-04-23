"""Phase 7 Guardrails T4 — ``routers/chat.py`` wiring.

Covers the four router-level acceptance criteria for Task T4:

1. **Request override wins over env** — ``body.guardrails_strict=True`` with
   ``settings.guardrails_strict=False`` still persists the guardrails blob
   on the assistant ``chat_message_logs`` row.
2. **Env fallback** — body omits ``guardrails_strict``; env flag is ``True``
   → router treats the turn as strict and persists the blob.
3. **Backward-compat / strict off** — both sides off → ``metadata_json``
   DOES NOT contain the ``"guardrails"`` key (existing chat flow undisturbed).
4. **Refusal path** — strict on + zero retrieval → the orchestrator emits a
   refusal envelope (``refusal_reason="no_retrieval"``,
   ``top_retrieval_score=0.0``) and the router both streams the canned
   refusal text AND persists the metadata blob.

Test strategy
-------------
We fully stub ``routers.chat.orchestrate_stream`` so we can drive the
assistant-side SSE stream + ``done`` payload synchronously, without a real
LLM / retrieval stack. The contract under test here is purely the wiring
between ``ChatRequest.guardrails_strict``, ``settings.guardrails_strict``,
the orchestrator kwarg, and the persisted ``ChatMessageLog.metadata_json``
— not the behaviour of the guardrails helpers themselves (already covered
by ``tests/services/agent/test_turn_pipeline_guardrails.py``).

``ensure_llm_ready`` is also patched to a no-op so the tests don't need a
real LLM provider configured to reach the handler body.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from models.chat_message import ChatMessageLog
from services.agent.agents.prompts import REFUSAL_TEMPLATE


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Per-test ``AsyncClient`` + isolated SQLite DB.

    Mirrors the fixture used by ``test_upload_screenshot.py`` so the chat
    router exercises the real auth → get_db → course_access dependency
    graph, but against a clean ephemeral database.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-chat-guard-", suffix=".db")
    os.close(fd)

    test_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
        pool_pre_ping=False,
        poolclass=NullPool,
    )
    test_session_factory = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def _override_get_db():
        async with test_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    app.state.test_session_factory = test_session_factory
    original_async_session = database_module.async_session
    database_module.async_session = test_session_factory

    # LLM-readiness guard is orthogonal to what we're testing — neutralise
    # it so the tests can run without a configured provider.
    import routers.chat as _chat_mod

    async def _noop_ready(_feature_name: str, *, allow_degraded: bool = False) -> None:
        return None

    monkeypatch.setattr(_chat_mod, "ensure_llm_ready", _noop_ready)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, test_session_factory

    app.dependency_overrides.pop(get_db, None)
    database_module.async_session = original_async_session
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")
    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _create_course(client: AsyncClient, name: str = "Guardrails Course") -> str:
    """Seed a course through the public API so the chat endpoint's access
    check finds it owned by the single-user fallback identity."""
    resp = await client.post(
        "/api/courses/", json={"name": name, "description": "test"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _install_fake_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    content: str,
    guardrails: dict | None,
) -> dict[str, Any]:
    """Replace ``routers.chat.orchestrate_stream`` with a minimal stub.

    The stub yields one ``message`` event carrying ``content`` and one
    ``done`` event carrying the usual envelope plus (optionally) the
    ``guardrails`` blob. Captures the ``guardrails_strict`` kwarg the
    router passed so tests can assert the resolution precedence.
    """

    captured: dict[str, Any] = {}

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict]:
        captured["kwargs"] = kwargs
        yield {"event": "message", "data": json.dumps({"content": content})}
        done_payload: dict[str, Any] = {
            "status": "complete",
            "session_id": str(kwargs.get("session_id")),
            "response": content,
            "agent": "tutor",
            "intent": "learn",
            "tokens": 0,
            "actions": [],
            "tool_calls": [],
            "provenance": None,
            "verifier": None,
            "verifier_diagnostics": None,
            "task_link": None,
            "reflection": None,
            "layout_simplification": None,
            "is_mock": False,
        }
        if guardrails is not None:
            done_payload["guardrails"] = guardrails
        yield {"event": "done", "data": json.dumps(done_payload)}

    import routers.chat as _chat_mod

    monkeypatch.setattr(_chat_mod, "orchestrate_stream", fake_stream)
    return captured


async def _consume_sse(client: AsyncClient, body: dict) -> str:
    """POST to the chat endpoint and return the concatenated SSE body.

    We don't assert event ordering here — the existing SSE streaming
    behaviour is covered elsewhere. We just want to drive the handler to
    completion so the post-stream persistence path fires.
    """
    resp = await client.post("/api/chat/", json=body)
    assert resp.status_code == 200, resp.text
    return resp.text


async def _fetch_assistant_row(
    session_factory: async_sessionmaker,
) -> ChatMessageLog:
    """Return the single assistant-side row written during the turn."""
    async with session_factory() as db:
        result = await db.execute(
            select(ChatMessageLog).where(ChatMessageLog.role == "assistant")
        )
        rows = result.scalars().all()
    assert len(rows) == 1, f"expected exactly one assistant row, got {len(rows)}"
    return rows[0]


# ── Tests ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_flag_true_overrides_env_false(client, monkeypatch):
    """``body.guardrails_strict=True`` wins over env False.

    The persisted assistant row must carry ``metadata_json["guardrails"]``
    with ``strict_mode=True`` — proof that the router fed the override all
    the way down to persistence.
    """
    ac, session_factory = client

    from config import settings as _settings

    monkeypatch.setattr(_settings, "guardrails_strict", False)

    guardrails_blob = {
        "answer": "Generators are lazy iterators.",
        "confidence": 4,
        "citations": [1],
        "citation_chunks": [
            {"id": "doc-1", "source_file": "realpython.md", "snippet": "yield ..."}
        ],
        "refusal_reason": None,
        "top_retrieval_score": 0.81,
        "strict_mode": True,
    }
    captured = _install_fake_orchestrator(
        monkeypatch,
        content="Generators are lazy iterators.",
        guardrails=guardrails_blob,
    )

    course_id = await _create_course(ac)

    await _consume_sse(
        ac,
        {
            "course_id": course_id,
            "message": "explain generators",
            "guardrails_strict": True,
        },
    )

    # Router must have resolved True and forwarded it.
    assert captured["kwargs"]["guardrails_strict"] is True

    row = await _fetch_assistant_row(session_factory)
    assert row.metadata_json is not None
    assert "guardrails" in row.metadata_json
    assert row.metadata_json["guardrails"]["strict_mode"] is True
    assert row.metadata_json["guardrails"]["confidence"] == 4
    assert row.metadata_json["guardrails"]["citations"] == [1]


@pytest.mark.asyncio
async def test_request_flag_none_falls_back_to_env(client, monkeypatch):
    """``body.guardrails_strict`` omitted → router falls back to env flag.

    With ``settings.guardrails_strict=True`` this must still route the
    turn through strict mode and persist ``strict_mode=True``.
    """
    ac, session_factory = client

    from config import settings as _settings

    monkeypatch.setattr(_settings, "guardrails_strict", True)

    guardrails_blob = {
        "answer": "Answer text.",
        "confidence": 3,
        "citations": [],
        "citation_chunks": [],
        "refusal_reason": None,
        "top_retrieval_score": 0.7,
        "strict_mode": True,
    }
    captured = _install_fake_orchestrator(
        monkeypatch,
        content="Answer text.",
        guardrails=guardrails_blob,
    )

    course_id = await _create_course(ac)

    await _consume_sse(
        ac,
        {
            "course_id": course_id,
            "message": "ask something",
            # no ``guardrails_strict`` key → None → env fallback
        },
    )

    assert captured["kwargs"]["guardrails_strict"] is True

    row = await _fetch_assistant_row(session_factory)
    assert row.metadata_json is not None
    assert row.metadata_json["guardrails"]["strict_mode"] is True


@pytest.mark.asyncio
async def test_strict_mode_off_does_not_write_guardrails_metadata(client, monkeypatch):
    """Strict off on both sides → no ``guardrails`` key on the persisted row.

    Backward-compat: existing chat flow must be byte-identical in terms of
    metadata shape. Even if the orchestrator were to emit a ``guardrails``
    field (it won't, but defence-in-depth), the router must not copy it
    across because strict was not effective for this turn.
    """
    ac, session_factory = client

    from config import settings as _settings

    monkeypatch.setattr(_settings, "guardrails_strict", False)

    _install_fake_orchestrator(
        monkeypatch,
        content="Plain response.",
        guardrails=None,
    )

    course_id = await _create_course(ac)

    await _consume_sse(
        ac,
        {
            "course_id": course_id,
            "message": "hi",
            "guardrails_strict": False,
        },
    )

    row = await _fetch_assistant_row(session_factory)
    assert row.metadata_json is not None
    assert "guardrails" not in row.metadata_json


@pytest.mark.asyncio
async def test_no_retrieval_writes_refusal_metadata(client, monkeypatch):
    """Strict on + empty retrieval → refusal envelope persisted.

    Simulates what ``_apply_guardrails_pre`` + ``_apply_guardrails_post``
    would produce when ``content_docs`` is empty: a refusal blob with
    ``refusal_reason="no_retrieval"`` and ``top_retrieval_score=0.0``,
    plus the canned ``REFUSAL_TEMPLATE`` as the streamed answer text.
    """
    ac, session_factory = client

    from config import settings as _settings

    monkeypatch.setattr(_settings, "guardrails_strict", False)

    refusal_blob = {
        "answer": None,
        "confidence": None,
        "citations": [],
        "citation_chunks": [],
        "refusal_reason": "no_retrieval",
        "top_retrieval_score": 0.0,
        "strict_mode": True,
    }
    _install_fake_orchestrator(
        monkeypatch,
        content=REFUSAL_TEMPLATE,
        guardrails=refusal_blob,
    )

    course_id = await _create_course(ac)

    body_text = await _consume_sse(
        ac,
        {
            "course_id": course_id,
            "message": "something not in the corpus",
            "guardrails_strict": True,
        },
    )

    # The SSE body should contain at least the opening words of the refusal
    # template, streamed via the ``message`` event.
    refusal_prefix = REFUSAL_TEMPLATE.splitlines()[0]
    assert refusal_prefix in body_text

    row = await _fetch_assistant_row(session_factory)
    assert row.metadata_json is not None
    assert row.metadata_json["guardrails"]["refusal_reason"] == "no_retrieval"
    assert row.metadata_json["guardrails"]["top_retrieval_score"] == 0.0
    assert row.metadata_json["guardrails"]["strict_mode"] is True
    # The streamed refusal template must also be what we stored as content.
    assert REFUSAL_TEMPLATE.splitlines()[0] in row.content
