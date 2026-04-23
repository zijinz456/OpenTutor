"""Unit tests for ``services.voice.whisper_client.transcribe_audio``.

All tests stub ``AsyncOpenAI`` inside the module under test — no
network calls. Each test exercises one techlead verification criterion
from ``plan/voice_whisper_phase8.md`` T1.

Covers:
    * Happy path — success returns ``{text, language, duration_ms}``
      with Whisper's ``"english"`` normalised to ISO 639-1 ``"en"``.
    * Language hint is forwarded to the SDK as a ``language=`` kwarg.
    * SDK exceptions are folded into a structured dict (no bubble).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from services.voice import whisper_client


def _install_fake_openai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    resp: Any = None,
    raises: Exception | None = None,
) -> list[dict[str, Any]]:
    """Patch ``AsyncOpenAI`` in ``whisper_client`` module.

    Returns a recording list — each call to ``.audio.transcriptions
    .create(...)`` appends its kwargs so tests can assert the language
    hint made it through. If ``raises`` is set, the fake create coro
    raises that exception instead of returning ``resp``.
    """

    calls: list[dict[str, Any]] = []

    async def fake_create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        if raises is not None:
            raise raises
        return resp

    fake_client = MagicMock()
    fake_client.audio.transcriptions.create = fake_create

    def fake_ctor(*_args: Any, **_kwargs: Any) -> Any:
        return fake_client

    monkeypatch.setattr(whisper_client, "AsyncOpenAI", fake_ctor)
    return calls


class _FakeVerboseJsonResponse:
    """Minimal stand-in for the SDK's ``Transcription`` object.

    Verbose-json responses expose ``.text``, ``.language``, ``.duration``
    as plain attributes — the SDK types them with Pydantic but the test
    only needs duck-typed getattr access, which ``transcribe_audio``
    uses explicitly.
    """

    def __init__(self, text: str, language: str | None, duration: float | None):
        self.text = text
        self.language = language
        self.duration = duration


@pytest.mark.asyncio
async def test_transcribe_audio_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path — verbose_json success returns populated dict."""

    resp = _FakeVerboseJsonResponse(
        text="hello world",
        language="english",
        duration=1.234,
    )
    _install_fake_openai(monkeypatch, resp=resp)

    out = await whisper_client.transcribe_audio(
        audio_bytes=b"fake-audio-bytes",
        content_type="audio/webm",
    )

    assert out["text"] == "hello world"
    # verbose_json "english" → ISO 639-1 "en"
    assert out["language"] == "en"
    # 1.234 s → 1234 ms
    assert out["duration_ms"] == 1234
    assert out["error"] is None


@pytest.mark.asyncio
async def test_transcribe_audio_with_language_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Language hint is forwarded to the SDK as ``language=`` kwarg."""

    resp = _FakeVerboseJsonResponse(
        text="привіт світ",
        language="ukrainian",
        duration=0.5,
    )
    calls = _install_fake_openai(monkeypatch, resp=resp)

    out = await whisper_client.transcribe_audio(
        audio_bytes=b"fake-audio-bytes",
        content_type="audio/webm",
        language_hint="uk",
    )

    assert len(calls) == 1
    assert calls[0].get("language") == "uk"
    assert calls[0]["model"] == "whisper-1"
    assert out["text"] == "привіт світ"
    assert out["language"] == "uk"


@pytest.mark.asyncio
async def test_transcribe_audio_api_error_returns_error_dict_not_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK exceptions are folded into the response dict; no bubble."""

    _install_fake_openai(monkeypatch, raises=Exception("API down"))

    out = await whisper_client.transcribe_audio(
        audio_bytes=b"fake-audio-bytes",
        content_type="audio/webm",
    )

    assert out["text"] == ""
    assert out["language"] is None
    assert out["duration_ms"] is None
    assert out["error"] == "API down"
