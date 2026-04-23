"""Integration tests for ``POST /api/voice/transcribe`` (Phase 8 T2).

Covers the six router-level criteria from ``plan/voice_whisper_phase8.md``:

1. Happy path — 100 KiB webm → 200 with text / language / duration_ms.
2. Size cap — 12 MiB body → 413.
3. MIME guard — ``audio/mp3`` (not in whitelist) → 415.
4. Idempotency — same bytes twice → Whisper client invoked once.
5. Rate limit — 11th unique clip within 60 s → 429.
6. Whisper error — ``error`` field populated → 502 to the client.

Every test monkeypatches ``transcribe_audio`` on the router module
(matching how ``routers.voice`` imports it) so no real OpenAI call is
issued. A per-test SQLite fixture keeps ``get_current_user`` happy —
the dep resolves a row on first call and we don't want those writes
bleeding into the main DB.
"""

from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app


# -- Fixtures -----------------------------------------------------------


def _make_webm(size_bytes: int) -> bytes:
    """Build a byte blob of exactly ``size_bytes`` with a plausible webm
    header. The Whisper client is mocked, so only the length (for the
    size cap) and a non-empty body matter."""

    # EBML header magic — MediaRecorder's webm output starts with 1A 45 DF A3.
    webm_sig = b"\x1a\x45\xdf\xa3"
    if size_bytes < len(webm_sig):
        return webm_sig[:size_bytes]
    return webm_sig + b"\x00" * (size_bytes - len(webm_sig))


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Per-test ``AsyncClient`` with an isolated SQLite DB.

    Mirrors the upload_screenshot fixture — auth dep resolves a local
    user on first call, and we want that write against a throwaway DB.
    Also clears module-level rate-limit + cache state so each test
    starts from a clean bucket.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-voice-", suffix=".db")
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

    # Clear voice router state so each test starts with a clean bucket /
    # cache — otherwise a prior test's successful POSTs would push the
    # rate-limit test over the limit a request too early.
    import routers.voice as _voice

    _voice._RATE_LIMIT_STATE.clear()
    _voice._RESULT_CACHE.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    database_module.async_session = original_async_session
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")
    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _mock_transcribe(monkeypatch, result: dict) -> dict[str, int]:
    """Patch ``transcribe_audio`` on the router module and return a
    counter dict so callers can assert call counts.
    """

    import routers.voice as _voice

    counter = {"calls": 0}

    async def _fake_transcribe(audio_bytes, content_type, language_hint=None):  # noqa: ARG001
        counter["calls"] += 1
        return result

    monkeypatch.setattr(_voice, "transcribe_audio", _fake_transcribe)
    return counter


# -- 1. Happy path ------------------------------------------------------


@pytest.mark.asyncio
async def test_post_transcribe_audio_success(client, monkeypatch):
    """100 KiB webm → 200 with text / language / duration_ms."""

    counter = _mock_transcribe(
        monkeypatch,
        {"text": "hello", "language": "en", "duration_ms": 1500, "error": None},
    )

    webm_bytes = _make_webm(100 * 1024)
    resp = await client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", webm_bytes, "audio/webm")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text"] == "hello"
    assert body["language"] == "en"
    assert body["duration_ms"] == 1500
    assert body.get("error") is None
    assert counter["calls"] == 1


# -- 2. Size cap --------------------------------------------------------


@pytest.mark.asyncio
async def test_post_transcribe_oversized_413(client, monkeypatch):
    """12 MiB webm body → 413."""

    _mock_transcribe(
        monkeypatch,
        {"text": "", "language": None, "duration_ms": None, "error": None},
    )

    big = _make_webm(12 * 1024 * 1024)
    resp = await client.post(
        "/api/voice/transcribe",
        files={"file": ("big.webm", big, "audio/webm")},
    )
    assert resp.status_code == 413, resp.text
    body = resp.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert "too large" in detail.get("detail", "").lower()
    else:
        assert "too large" in str(body).lower()


# -- 3. MIME unsupported ------------------------------------------------


@pytest.mark.asyncio
async def test_post_transcribe_unsupported_mime_415(client, monkeypatch):
    """Content-Type: audio/mp3 (not in whitelist) → 415."""

    _mock_transcribe(
        monkeypatch,
        {"text": "", "language": None, "duration_ms": None, "error": None},
    )

    resp = await client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.mp3", b"ID3\x03\x00\x00\x00", "audio/mp3")},
    )
    assert resp.status_code == 415, resp.text
    # The allowed list should appear in the error message.
    assert "audio/webm" in resp.text


# -- 4. Idempotency cache ----------------------------------------------


@pytest.mark.asyncio
async def test_post_transcribe_idempotency_cached(client, monkeypatch):
    """Same bytes posted twice → whisper client called exactly once."""

    counter = _mock_transcribe(
        monkeypatch,
        {"text": "cached reply", "language": "en", "duration_ms": 800, "error": None},
    )

    webm = _make_webm(50 * 1024)
    first = await client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", webm, "audio/webm")},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", webm, "audio/webm")},
    )
    assert second.status_code == 200, second.text

    assert counter["calls"] == 1, (
        f"expected 1 whisper call, got {counter['calls']} (cache miss)"
    )
    assert first.json() == second.json()


# -- 5. Rate limit ------------------------------------------------------


@pytest.mark.asyncio
async def test_post_transcribe_rate_limit_11th_429(client, monkeypatch):
    """10 POSTs in a 60 s window succeed, 11th returns 429.

    Uses monkeypatched ``time.monotonic`` so the test completes in
    milliseconds instead of waiting a real 60 s window.
    """

    _mock_transcribe(
        monkeypatch,
        {"text": "ok", "language": "en", "duration_ms": 100, "error": None},
    )

    import routers.voice as _voice

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(_voice.time, "monotonic", lambda: fake_now["t"])

    # 10 successful requests — each body is unique so the TTL cache never
    # short-circuits the rate-limit check.
    for i in range(10):
        body = _make_webm(2 * 1024 + i)
        resp = await client.post(
            "/api/voice/transcribe",
            files={"file": (f"clip{i}.webm", body, "audio/webm")},
        )
        assert resp.status_code == 200, f"req {i}: {resp.text}"

    # 11th — over the limit.
    resp11 = await client.post(
        "/api/voice/transcribe",
        files={"file": ("clip11.webm", _make_webm(2 * 1024 + 99), "audio/webm")},
    )
    assert resp11.status_code == 429, resp11.text
    assert "slow down" in resp11.text.lower()
    assert "10 voice transcriptions" in resp11.text.lower()


# -- 6. Whisper error ---------------------------------------------------


@pytest.mark.asyncio
async def test_post_transcribe_whisper_error_502(client, monkeypatch):
    """Whisper client returns ``error=...`` → 502 to the client."""

    _mock_transcribe(
        monkeypatch,
        {"text": "", "language": None, "duration_ms": None, "error": "API down"},
    )

    webm = _make_webm(10 * 1024)
    resp = await client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", webm, "audio/webm")},
    )
    assert resp.status_code == 502, resp.text
    body = resp.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert "transcription failed" in detail.get("detail", "").lower()
        assert detail.get("hint") == "Try again"
    else:
        assert "transcription failed" in str(body).lower()
