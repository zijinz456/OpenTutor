"""Unit tests for ``services.screenshot.vision_extractor``.

All tests stub the vision LLM via ``monkeypatch`` on ``get_llm_client``
inside the extractor module — no network calls. The stub drives every
failure path deterministically (valid JSON, invalid JSON, transport
raise, PII payloads).

Covers the T1 techlead verification criteria from
``plan/screenshot_drill_phase4.md``:
- Happy path: valid ``CardBatchWide`` → 3-5 :class:`CardCandidate`.
- PII filter (API key): card containing ``sk-…`` is dropped, counter
  bumps, ``screenshot_pii_dropped`` warning logged.
- PII filter (email): email in ``front`` → dropped.
- Retry-once on JSON parse fail: first call bad JSON, second valid
  → 2 attempts, parsed cards returned.
- Never-raises on transport error: fake client raises
  ``RuntimeError`` → ``([], 0)`` and ``logger.exception`` fired.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from schemas.curriculum import CardCandidate
from services.screenshot import vision_extractor
from services.screenshot.vision_extractor import extract_cards_from_image


# ── fixtures / helpers ─────────────────────────────────────


def _valid_payload(
    n: int = 3, back_override: str | None = None, front_override: str | None = None
) -> dict[str, Any]:
    """Build a minimal-but-valid ``CardBatchWide`` payload with ``n``
    cards. ``back_override`` / ``front_override`` let individual tests
    inject PII strings without rebuilding the whole payload."""

    cards: list[dict[str, Any]] = []
    for i in range(n):
        cards.append(
            {
                "front": front_override if i == 0 and front_override else f"Q{i}",
                "back": back_override if i == 0 and back_override else f"A{i}",
                "concept_slug": "race-condition" if i == 0 else None,
            }
        )
    return {"cards": cards}


def _install_fake_vision_llm(
    monkeypatch: pytest.MonkeyPatch,
    responses: list[str],
) -> list[dict[str, Any]]:
    """Replace ``get_llm_client`` so ``client.chat`` returns each string
    in ``responses`` in order. Returns a list of recorded call kwargs
    (system, user, images) for assertion on call count + image
    payload shape."""

    calls: list[dict[str, Any]] = []
    response_iter = iter(responses)

    async def fake_chat(
        system: str, user: str, images: list[dict[str, str]] | None = None
    ) -> tuple[str, dict[str, int]]:
        calls.append({"system": system, "user": user, "images": images})
        return next(response_iter), {"input_tokens": 0, "output_tokens": 0}

    fake_client = MagicMock()
    fake_client.chat = fake_chat

    monkeypatch.setattr(
        vision_extractor, "get_llm_client", lambda _variant=None: fake_client
    )
    return calls


def _install_raising_vision_llm(
    monkeypatch: pytest.MonkeyPatch, exc: Exception
) -> list[dict[str, Any]]:
    """Replace ``get_llm_client`` with a ``chat`` that raises ``exc``
    on every call. Used to prove the never-raises contract on
    transport errors."""

    calls: list[dict[str, Any]] = []

    async def raising_chat(
        system: str, user: str, images: list[dict[str, str]] | None = None
    ) -> tuple[str, dict[str, int]]:
        calls.append({"system": system, "user": user, "images": images})
        raise exc

    fake_client = MagicMock()
    fake_client.chat = raising_chat

    monkeypatch.setattr(
        vision_extractor, "get_llm_client", lambda _variant=None: fake_client
    )
    return calls


# ── 1. happy path ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_returns_3_to_5_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LLM returns a valid 3-card batch → we get back 3
    :class:`CardCandidate` instances, zero dropped."""

    payload = json.dumps(_valid_payload(n=3))
    calls = _install_fake_vision_llm(monkeypatch, [payload])

    cards, dropped = await extract_cards_from_image(
        image_bytes=b"fakepngdata",
        mime="image/png",
        course_id="c1",
        slug_hint=["race-condition", "deadlock"],
    )

    assert len(cards) == 3
    assert dropped == 0
    assert all(isinstance(c, CardCandidate) for c in cards)
    assert cards[0].front == "Q0"
    assert cards[0].concept_slug == "race-condition"
    # Image payload shape: single block with base64 data + correct MIME.
    assert len(calls) == 1
    images = calls[0]["images"]
    assert images is not None
    assert len(images) == 1
    assert images[0]["media_type"] == "image/png"
    assert images[0]["data"]  # non-empty base64 string


# ── 2. PII filter — API key ────────────────────────────────


@pytest.mark.asyncio
async def test_pii_api_key_stripped(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A card whose ``back`` field contains an OpenAI-style ``sk-…``
    key must be dropped by the PII regex, counter bumps to 1, and a
    ``screenshot_pii_dropped`` WARNING is logged."""

    payload = json.dumps(
        _valid_payload(
            n=3,
            back_override="api key is sk-abc123def456ghi789jkl012mno345",
        )
    )
    _install_fake_vision_llm(monkeypatch, [payload])
    caplog.set_level(logging.WARNING, logger="services.screenshot.vision_extractor")

    cards, dropped = await extract_cards_from_image(
        image_bytes=b"fakepngdata",
        mime="image/png",
        course_id="c1",
    )

    # 1 of 3 cards dropped, 2 kept, and the leaked string is NOT in any
    # surviving ``back`` field.
    assert len(cards) == 2
    assert dropped == 1
    assert all("sk-abc123" not in c.back for c in cards)
    # Warning log fired with the documented event name.
    assert any("screenshot_pii_dropped" in rec.message for rec in caplog.records), (
        "expected screenshot_pii_dropped warning"
    )


# ── 3. PII filter — email ─────────────────────────────────


@pytest.mark.asyncio
async def test_pii_email_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A card whose ``front`` contains an email address must be
    dropped by the email regex."""

    payload = json.dumps(
        _valid_payload(
            n=3,
            front_override="How did <user@example.com> solve it?",
        )
    )
    _install_fake_vision_llm(monkeypatch, [payload])

    cards, dropped = await extract_cards_from_image(
        image_bytes=b"fakepngdata",
        mime="image/png",
        course_id="c1",
    )

    assert dropped == 1
    assert len(cards) == 2
    assert all("user@example.com" not in c.front for c in cards)


# ── 4. retry on JSON parse fail ───────────────────────────


@pytest.mark.asyncio
async def test_retry_once_on_json_parse_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First LLM response is unparseable; second is a valid 3-card
    batch. Function must return 3 cards and have called the LLM
    exactly twice."""

    bad = "not valid json {"
    good = json.dumps(_valid_payload(n=3))
    calls = _install_fake_vision_llm(monkeypatch, [bad, good])

    cards, dropped = await extract_cards_from_image(
        image_bytes=b"fakepngdata",
        mime="image/png",
        course_id="c1",
    )

    assert len(cards) == 3
    assert dropped == 0
    assert len(calls) == 2, "expected exactly one retry on parse failure"


# ── 5. never-raises on transport error ────────────────────


@pytest.mark.asyncio
async def test_never_raises_on_transport_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A transport-level failure (``RuntimeError("network down")`` from
    the LLM client) must NOT propagate. The extractor returns
    ``([], 0)`` and ``logger.exception`` fires on the failing call.
    Transport errors do NOT retry (sticky rate-limit policy), so the
    fake client is called exactly once."""

    calls = _install_raising_vision_llm(monkeypatch, RuntimeError("network down"))
    caplog.set_level(logging.ERROR, logger="services.screenshot.vision_extractor")

    cards, dropped = await extract_cards_from_image(
        image_bytes=b"fakepngdata",
        mime="image/png",
        course_id="c1",
    )

    assert cards == []
    assert dropped == 0
    assert len(calls) == 1, "transport errors must not retry"
    # logger.exception writes at ERROR level and includes exc_info.
    assert any(
        rec.levelno == logging.ERROR and rec.exc_info is not None
        for rec in caplog.records
    ), "expected logger.exception on transport failure"
