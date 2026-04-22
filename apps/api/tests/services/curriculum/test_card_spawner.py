"""Unit tests for ``services.curriculum.card_spawner``.

All tests stub the LLM via ``monkeypatch`` on ``get_llm_client`` — no
network calls to any real provider. The LLM stub lets us drive every
failure path deterministically (valid JSON, garbage, over-cap, hang,
etc.).

Covers the T4 techlead verification criteria from
``plan/url_autocurriculum_v2.1.md``:
- Happy path: valid ``CardBatch`` → returns parsed candidates.
- Truncation: schema + code both cap at 3, proven in tandem.
- Retry-then-success: first call garbage, second call valid → retry wins.
- Total failure: both attempts garbage → ``[]`` with warning log.
- Timeout: LLM hangs beyond the 8s budget → ``[]``, bounded by
  ``asyncio.wait_for``.
- Trivial input: response ≤100 chars → ``[]`` WITHOUT calling the LLM.
- Markdown fence unwrap: ```json wrapping parses cleanly (T1 parity).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from schemas.curriculum import CardCandidate
from services.curriculum import card_spawner
from services.curriculum.card_spawner import extract_card_candidates


# ── fixtures / helpers ─────────────────────────────────────


def _long_response(seed: str = "Python generators produce values lazily") -> str:
    """Build a response string comfortably over the 100-char trivial
    threshold so the LLM path is exercised. Content itself is irrelevant
    because we stub the LLM — we just need to bypass the short-circuit.
    """
    text = (
        f"{seed}. "
        "They let a function pause and resume, emitting a sequence of "
        "values one at a time via the yield keyword. This keeps memory "
        "usage flat regardless of how long the stream is, and enables "
        "streaming transformations over very large inputs."
    )
    assert len(text.strip()) >= 100, "test fixture precondition"
    return text


def _valid_batch_payload(n: int = 2) -> dict[str, Any]:
    """A minimal-but-valid CardBatch payload with ``n`` cards (n ≤ 3)."""
    cards: list[dict[str, Any]] = []
    for i in range(n):
        cards.append(
            {
                "front": f"What is generator concept #{i}?",
                "back": f"It is a lazy sequence producer, example #{i}.",
                "concept_slug": "generators" if i == 0 else None,
            }
        )
    return {"cards": cards}


def _install_fake_llm(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
) -> list[str]:
    """Replace ``get_llm_client`` so ``client.extract`` returns each
    string in ``responses`` in order. Returns the captured user prompts
    for caller inspection (length = call count)."""

    calls: list[str] = []
    response_iter = iter(responses)

    async def fake_extract(system: str, user: str) -> tuple[str, dict[str, Any]]:
        calls.append(user)
        return next(response_iter), {}

    fake_client = MagicMock()
    fake_client.extract = fake_extract

    monkeypatch.setattr(
        card_spawner, "get_llm_client", lambda _variant=None: fake_client
    )
    return calls


def _install_hanging_llm(
    monkeypatch: pytest.MonkeyPatch, sleep_sec: float = 30.0
) -> list[str]:
    """Replace ``get_llm_client`` with an extract that sleeps forever.

    Used to prove that the ``asyncio.wait_for(..., timeout=8.0)`` wrapper
    in ``extract_card_candidates`` actually bounds the call, regardless
    of what the LLM does.
    """

    calls: list[str] = []

    async def hanging_extract(system: str, user: str) -> tuple[str, dict[str, Any]]:
        calls.append(user)
        await asyncio.sleep(sleep_sec)
        return "never reached", {}

    fake_client = MagicMock()
    fake_client.extract = hanging_extract

    monkeypatch.setattr(
        card_spawner, "get_llm_client", lambda _variant=None: fake_client
    )
    return calls


# ── happy path ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_returns_parsed_candidates_on_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM returns a valid 2-card batch → we get back 2
    ``CardCandidate`` instances with the expected fields."""

    payload = json.dumps(_valid_batch_payload(n=2))
    _install_fake_llm(monkeypatch, [payload])

    cards = await extract_card_candidates(
        response_text=_long_response(),
        chunk_ids=[uuid.uuid4(), uuid.uuid4()],
        course_id=uuid.uuid4(),
    )

    assert len(cards) == 2
    assert all(isinstance(c, CardCandidate) for c in cards)
    assert cards[0].front.startswith("What is generator concept #0")
    assert cards[0].concept_slug == "generators"
    assert cards[1].concept_slug is None


# ── truncation (≤3 cap, defense-in-depth) ──────────────────


@pytest.mark.asyncio
async def test_extract_enforces_max_three_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema ``CardBatch.cards = Field(max_length=3)`` enforces the cap
    at validation time. A payload of 5 cards therefore fails validation
    on the first attempt; if the retry also returns 5, we fall through
    to ``[]``. This test pins the schema-level guarantee AND then
    separately checks the code-level cap via a monkeypatched
    ``_parse_batch`` that yields a 5-card batch — proving the
    ``batch.cards[:_MAX_CARDS]`` slice at the return boundary."""

    # ── Part A: schema-level cap. Over-sized payload is rejected by
    # pydantic; both attempts fail → [].
    oversized = {"cards": _valid_batch_payload(n=3)["cards"] * 2}  # 6 cards
    _install_fake_llm(monkeypatch, [json.dumps(oversized), json.dumps(oversized)])
    cards = await extract_card_candidates(
        response_text=_long_response(),
        chunk_ids=[],
        course_id=uuid.uuid4(),
    )
    assert cards == [], "schema cap should reject 6-card payloads"

    # ── Part B: code-level cap. Simulate a world where _parse_batch
    # somehow produced a 5-card CardBatch (schema drift / future
    # relaxation). The public function must still return ≤3.
    class _StubBatch:
        def __init__(self, n: int) -> None:
            self.cards = [CardCandidate(front=f"Q{i}", back=f"A{i}") for i in range(n)]

    monkeypatch.setattr(card_spawner, "_parse_batch", lambda raw: _StubBatch(5))

    # LLM just needs to return *something* so _call_llm_once returns a
    # non-None raw — _parse_batch is stubbed, so content is ignored.
    _install_fake_llm(monkeypatch, ["irrelevant body"])

    cards = await extract_card_candidates(
        response_text=_long_response(),
        chunk_ids=[],
        course_id=uuid.uuid4(),
    )
    assert len(cards) == 3, "defensive [:3] slice must cap post-parse too"


# ── retry behaviour ────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_retries_once_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First LLM response is unparseable junk; second is a valid batch.
    Function must return the second attempt's cards and have called the
    LLM exactly twice."""

    valid = json.dumps(_valid_batch_payload(n=1))
    prompts = _install_fake_llm(monkeypatch, ["not json at all", valid])

    cards = await extract_card_candidates(
        response_text=_long_response(),
        chunk_ids=[],
        course_id=uuid.uuid4(),
    )

    assert len(cards) == 1
    assert len(prompts) == 2, "expected exactly one retry"


@pytest.mark.asyncio
async def test_extract_returns_empty_after_both_attempts_fail(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Both attempts garbage → ``[]`` (not None) with a warning log.
    Confirms the critic-flagged "never raise, always return list"
    contract."""

    prompts = _install_fake_llm(monkeypatch, ["garbage one", "garbage two"])
    caplog.set_level(logging.WARNING, logger="services.curriculum.card_spawner")

    cards = await extract_card_candidates(
        response_text=_long_response(),
        chunk_ids=[],
        course_id=uuid.uuid4(),
    )

    assert cards == []
    assert isinstance(cards, list)
    assert len(prompts) == 2
    assert any("all 2 attempts failed" in rec.message for rec in caplog.records), (
        "expected summarising warning log on total failure"
    )


# ── timeout / hang safety ──────────────────────────────────


@pytest.mark.asyncio
async def test_extract_returns_empty_on_llm_hang(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If the LLM hangs past the 8s budget, the function must return
    ``[]`` without raising. We shorten the budget for the test so it
    runs fast; the real ``_TIMEOUT_SEC`` is 8.0."""

    # Reduce the wall-clock budget so this test is quick. We still prove
    # the ``asyncio.wait_for`` wrapper bounds the call — the point is
    # "function honours the timeout attribute", not "exactly 8 seconds".
    monkeypatch.setattr(card_spawner, "_TIMEOUT_SEC", 0.3)

    calls = _install_hanging_llm(monkeypatch, sleep_sec=5.0)
    caplog.set_level(logging.WARNING, logger="services.curriculum.card_spawner")

    # Outer wait_for enforces the test harness budget too — if our
    # function's own wait_for didn't fire, the test would still fail
    # rather than hang the suite.
    cards = await asyncio.wait_for(
        extract_card_candidates(
            response_text=_long_response(),
            chunk_ids=[],
            course_id=uuid.uuid4(),
        ),
        timeout=2.0,
    )

    assert cards == []
    assert len(calls) == 1  # we started one LLM call, then got cancelled
    assert any("timed out" in rec.message for rec in caplog.records), (
        "expected a warning log on timeout"
    )


# ── trivial-response short-circuit (no LLM call at all) ────


@pytest.mark.asyncio
async def test_extract_skips_llm_for_trivial_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Response text of just "ok" must yield ``[]`` WITHOUT touching the
    LLM. This is the key optimisation — no provider calls on
    acknowledgments."""

    calls = _install_fake_llm(monkeypatch, ["should never be returned"])

    cards = await extract_card_candidates(
        response_text="ok",
        chunk_ids=[],
        course_id=uuid.uuid4(),
    )

    assert cards == []
    assert len(calls) == 0, "LLM must not be called for trivial input"


@pytest.mark.asyncio
async def test_extract_skips_llm_for_whitespace_only_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Whitespace-only responses also count as trivial — ``.strip()``
    applied before the length check prevents "     " from sneaking
    through."""

    calls = _install_fake_llm(monkeypatch, ["should never be returned"])

    cards = await extract_card_candidates(
        response_text="   \n\t  \n\n  ",
        chunk_ids=[],
        course_id=uuid.uuid4(),
    )

    assert cards == []
    assert len(calls) == 0


# ── markdown fence unwrap (T1 parity) ──────────────────────


@pytest.mark.asyncio
async def test_extract_strips_markdown_json_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLMs wrap JSON in ```json fences despite system-prompt orders.
    The extractor grabs the span ``{..}`` from the first ``{`` to the
    last ``}`` — confirm that wrapping does not break parsing."""

    payload = _valid_batch_payload(n=2)
    fenced = f"```json\n{json.dumps(payload)}\n```"
    _install_fake_llm(monkeypatch, [fenced])

    cards = await extract_card_candidates(
        response_text=_long_response(),
        chunk_ids=[],
        course_id=uuid.uuid4(),
    )

    assert len(cards) == 2
    assert cards[0].front.startswith("What is generator concept #0")


# ── prompt content sanity ──────────────────────────────────


@pytest.mark.asyncio
async def test_extract_embeds_course_id_and_chunk_count_in_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``course_id`` and the number of grounded chunks should appear in
    the prompt (as metadata hints), while the full response text is the
    source of facts. This is the plan's "prompt enrichment" contract."""

    payload = json.dumps(_valid_batch_payload(n=1))
    prompts = _install_fake_llm(monkeypatch, [payload])

    course_id = uuid.uuid4()
    chunks = [uuid.uuid4() for _ in range(4)]
    response = _long_response(seed="List comprehensions are syntactic sugar")

    await extract_card_candidates(
        response_text=response,
        chunk_ids=chunks,
        course_id=course_id,
    )

    assert len(prompts) == 1
    prompt = prompts[0]
    assert str(course_id) in prompt
    assert "grounded_chunks: 4" in prompt
    # Response content reaches the prompt body verbatim:
    assert "List comprehensions are syntactic sugar" in prompt
