"""Unit tests for the orchestrator's card-spawn hook (§14.5 v2.1 T5).

The hook itself is ``services.agent.orchestrator._maybe_spawn_card_task``
— a module-level helper extracted specifically so we can drive the
intent/length gate + background-task wiring without having to mock the
entire ``orchestrate_stream`` generator (routing, context loading, agent
stream, verifier, reflection — far too heavy for a meaningful unit
test).

Scope:

* **Gate** — LEARN + >200-char response → fires. Every other combo →
  returns ``None`` (no message_id, caller won't emit pending_cards).
* **Chunk ID extraction** — resilient to malformed ``content_docs``.
* **Background task wiring** — spawner is invoked, result lands in
  ``card_cache`` under the returned ``message_id``.
* **Spawner raising** — shouldn't happen (it promises never to), but
  if it does, hook falls back to ``cards=[]`` in the cache rather than
  letting the task crash silently without a cache entry.
"""

from __future__ import annotations

import uuid

import pytest

from schemas.curriculum import CardCandidate
from services.agent import card_cache
from services.agent.orchestrator import (
    _extract_chunk_ids,
    _maybe_spawn_card_task,
)
from services.agent.state import AgentContext, IntentType


# ── helpers ─────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_cache() -> None:
    card_cache.clear()
    yield
    card_cache.clear()


def _ctx(
    *,
    response: str = "",
    intent: IntentType = IntentType.LEARN,
    content_docs: list[dict] | None = None,
) -> AgentContext:
    """Build a minimal ``AgentContext`` shaped just enough for the hook."""
    ctx = AgentContext(
        user_id=uuid.uuid4(),
        course_id=uuid.uuid4(),
    )
    ctx.response = response
    ctx.intent = intent
    ctx.content_docs = content_docs or []
    return ctx


def _teaching_response() -> str:
    """Produce a >200-char response that trips the length gate."""
    body = (
        "Python generators are functions that produce values lazily using "
        "the yield keyword. They pause execution at each yield, keep local "
        "state, and resume on the next next() call. This keeps memory flat "
        "regardless of sequence size and enables infinite streams."
    )
    assert len(body) > 200, "fixture precondition: response must clear 200-char gate"
    return body


# ── gate tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_fires_on_learn_intent_and_long_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Happy path: LEARN + long response → msg_id returned, task queued.

    Must run under ``pytest.mark.asyncio`` because the happy-path branch
    calls ``asyncio.create_task`` which requires a running event loop.
    We stub the spawner to avoid hitting the real LLM plus complete the
    background task cleanly inside the test's loop.
    """

    async def fake_extract(response_text, chunk_ids, course_id):
        return []

    from services.curriculum import card_spawner as spawner_mod

    monkeypatch.setattr(spawner_mod, "extract_card_candidates", fake_extract)

    ctx = _ctx(response=_teaching_response(), intent=IntentType.LEARN)

    msg_id = _maybe_spawn_card_task(ctx)

    assert msg_id is not None
    assert isinstance(msg_id, uuid.UUID)

    # Let the stubbed background task complete so pytest doesn't warn
    # about unawaited coroutines and the cache entry materialises.
    cached = await card_cache.await_or_get(
        ctx.session_id,
        msg_id,
        timeout_s=2.0,
    )
    assert cached == []


def test_gate_skips_non_learn_intent() -> None:
    """PLAN/LAYOUT/GENERAL/ONBOARDING intents should not spawn cards.

    Sync test: all branches return ``None`` *before* reaching the
    ``asyncio.create_task`` call, so no event loop is needed.
    """
    for intent in (
        IntentType.PLAN,
        IntentType.LAYOUT,
        IntentType.GENERAL,
        IntentType.ONBOARDING,
    ):
        ctx = _ctx(response=_teaching_response(), intent=intent)
        assert _maybe_spawn_card_task(ctx) is None, (
            f"intent={intent.value} should not trigger card spawn"
        )


def test_gate_skips_short_response() -> None:
    """50-char 'OK got it' style response → no spawn even under LEARN.

    Sync: the length branch short-circuits before any ``create_task``.
    """
    ctx = _ctx(
        response="Got it. Let me know if you want to try a problem next.",
        intent=IntentType.LEARN,
    )
    # Length sanity check so the test is self-documenting.
    assert len(ctx.response) <= 200, "fixture precondition"
    assert _maybe_spawn_card_task(ctx) is None


def test_gate_skips_empty_response() -> None:
    """Empty response (agent crashed, nothing to extract from) → no spawn."""
    ctx = _ctx(response="", intent=IntentType.LEARN)
    assert _maybe_spawn_card_task(ctx) is None


# ── chunk_id extraction ─────────────────────────────────────


def test_extract_chunk_ids_from_valid_docs() -> None:
    """Docs with stringified UUIDs in ``id`` → parsed UUID list."""
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    docs = [
        {"id": str(u1), "content": "x"},
        {"id": str(u2), "content": "y"},
    ]
    out = _extract_chunk_ids(docs)
    assert out == [u1, u2]


def test_extract_chunk_ids_skips_malformed_entries() -> None:
    """Non-dicts, missing IDs, non-UUID strings → silently dropped."""
    u1 = uuid.uuid4()
    docs = [
        {"id": str(u1)},  # good
        {"id": "not-a-uuid"},  # bad — skipped
        {"content": "no id"},  # missing id — skipped
        "not-a-dict",  # wrong type — skipped
        {"id": None},  # falsy id — skipped
    ]
    out = _extract_chunk_ids(docs)
    assert out == [u1]


def test_extract_chunk_ids_empty_input() -> None:
    assert _extract_chunk_ids([]) == []


# ── background task wiring ──────────────────────────────────


@pytest.mark.asyncio
async def test_hook_populates_cache_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_maybe_spawn_card_task`` fires ``extract_card_candidates``;
    result lands in ``card_cache`` under the returned ``message_id``.
    """

    captured: dict = {}

    async def fake_extract(response_text, chunk_ids, course_id):
        captured["response_text"] = response_text
        captured["chunk_ids"] = chunk_ids
        captured["course_id"] = course_id
        return [
            CardCandidate(front="Q1", back="A1"),
            CardCandidate(front="Q2", back="A2"),
        ]

    # The hook imports the symbol lazily at call time inside the
    # ``_spawn_and_cache`` closure, so patch on the source module.
    from services.curriculum import card_spawner as spawner_mod

    monkeypatch.setattr(spawner_mod, "extract_card_candidates", fake_extract)

    u_chunk = uuid.uuid4()
    ctx = _ctx(
        response=_teaching_response(),
        intent=IntentType.LEARN,
        content_docs=[{"id": str(u_chunk), "content": "ctx"}],
    )

    msg_id = _maybe_spawn_card_task(ctx)
    assert msg_id is not None

    # Await the cache entry — this is exactly what the endpoint does.
    cached = await card_cache.await_or_get(
        ctx.session_id,
        msg_id,
        timeout_s=2.0,
    )
    assert cached is not None
    assert [c.front for c in cached] == ["Q1", "Q2"]

    # Verify the spawner received the right arguments.
    assert captured["response_text"] == ctx.response
    assert captured["chunk_ids"] == [u_chunk]
    assert captured["course_id"] == ctx.course_id


@pytest.mark.asyncio
async def test_hook_caches_empty_list_when_spawner_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spawner is supposed to never raise, but a future bug shouldn't
    leave the cache key unset — the frontend would otherwise poll for
    10s with no resolution. The hook's except branch puts ``[]`` so
    the endpoint returns promptly with ``{cards:[], reason:None}``.
    """

    async def fake_extract(response_text, chunk_ids, course_id):
        raise RuntimeError("simulated spawner blow-up")

    from services.curriculum import card_spawner as spawner_mod

    monkeypatch.setattr(spawner_mod, "extract_card_candidates", fake_extract)

    ctx = _ctx(response=_teaching_response(), intent=IntentType.LEARN)

    msg_id = _maybe_spawn_card_task(ctx)
    assert msg_id is not None

    cached = await card_cache.await_or_get(
        ctx.session_id,
        msg_id,
        timeout_s=2.0,
    )
    # Key IS populated (the hook swallowed the exception and wrote []),
    # not None. This is the critical assertion: a crashed spawner must
    # not leave consumers waiting forever.
    assert cached == []


@pytest.mark.asyncio
async def test_hook_caches_empty_list_when_spawner_returns_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spawner legitimately returning 0 cards is cached as [], not
    missing. Same endpoint behaviour as the raise path but via the
    happy control flow."""

    async def fake_extract(response_text, chunk_ids, course_id):
        return []

    from services.curriculum import card_spawner as spawner_mod

    monkeypatch.setattr(spawner_mod, "extract_card_candidates", fake_extract)

    ctx = _ctx(response=_teaching_response(), intent=IntentType.LEARN)
    msg_id = _maybe_spawn_card_task(ctx)
    assert msg_id is not None

    cached = await card_cache.await_or_get(
        ctx.session_id,
        msg_id,
        timeout_s=2.0,
    )
    assert cached == []


@pytest.mark.asyncio
async def test_hook_returns_unique_ids_per_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two consecutive teaching turns on the same session get distinct
    ``message_id``s — no overwrites between them."""

    async def fake_extract(response_text, chunk_ids, course_id):
        return [CardCandidate(front="x", back="y")]

    from services.curriculum import card_spawner as spawner_mod

    monkeypatch.setattr(spawner_mod, "extract_card_candidates", fake_extract)

    ctx1 = _ctx(response=_teaching_response(), intent=IntentType.LEARN)
    ctx2 = _ctx(response=_teaching_response(), intent=IntentType.LEARN)
    # Share the session_id so we know keys differ only in message_id.
    ctx2.session_id = ctx1.session_id

    m1 = _maybe_spawn_card_task(ctx1)
    m2 = _maybe_spawn_card_task(ctx2)

    assert m1 is not None and m2 is not None
    assert m1 != m2

    # Both land in the cache independently.
    c1 = await card_cache.await_or_get(ctx1.session_id, m1, timeout_s=2.0)
    c2 = await card_cache.await_or_get(ctx2.session_id, m2, timeout_s=2.0)
    assert c1 is not None and c2 is not None
