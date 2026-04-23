"""Integration tests for ``POST /upload/screenshot`` (Phase 4 T2).

Covers the plan's six router-level criteria:

1. Happy path — 100 KiB PNG → 200, 3 candidates, 16-char hash.
2. Size cap — 6 MiB body → 413 with the "too large" detail.
3. MIME guard — ``application/pdf`` → 415.
4. Rate limit — 6th POST in a 60 s window → 429.
5. Idempotency cache — same bytes twice → extractor called once.
6. Course not found → 404.

Every test monkeypatches ``extract_cards_from_image`` on the router
module (matching how ``routers.upload_screenshot`` imports it) so no
real LLM call is issued.
"""

from __future__ import annotations

import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from schemas.curriculum import CardCandidate


# ── Fixtures ────────────────────────────────────────────────────────────

# Minimal valid-enough PNG (8-byte signature + IHDR + IEND) so ``UploadFile``
# doesn't choke on content-type sniffing. The vision extractor itself is
# mocked so the actual bytes are never forwarded to a real provider.
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _make_png(size_bytes: int) -> bytes:
    """Build a byte blob that starts with the PNG signature and is exactly
    ``size_bytes`` long. Body after the signature is zero-filled — the
    vision extractor is mocked so the content never matters, only the
    length (for the size cap) and the signature prefix (so anyone
    sniffing MIME from the body sees PNG)."""

    if size_bytes < len(_PNG_SIG):
        return _PNG_SIG[:size_bytes]
    return _PNG_SIG + b"\x00" * (size_bytes - len(_PNG_SIG))


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Per-test ``AsyncClient`` with an isolated SQLite DB.

    Mirrors the fixture in ``test_upload_coursera.py`` so the router
    tests exercise the real dependency graph (auth dep → get_db →
    course access → extractor call site) without touching a shared
    database.
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-screenshot-", suffix=".db")
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

    # Clear module-level rate-limit + cache state so each test starts
    # from a clean bucket — otherwise a prior test's 5 requests would
    # push the next test's happy-path request to 429.
    import routers.upload_screenshot as _us

    _us._RATE_LIMIT_STATE.clear()
    _us._RESULT_CACHE.clear()

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


async def _create_course(client: AsyncClient, name: str = "Screenshot Course") -> str:
    resp = await client.post(
        "/api/courses/", json={"name": name, "description": "test"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _mock_extractor(
    monkeypatch, cards: list[CardCandidate], dropped: int = 0
) -> dict[str, int]:
    """Patch ``extract_cards_from_image`` on the router module and
    return a counter dict so callers can assert call counts.
    """

    import routers.upload_screenshot as _us

    counter = {"calls": 0}

    async def _fake_extract(image_bytes, mime, course_id, slug_hint=None):  # noqa: ARG001
        counter["calls"] += 1
        return cards, dropped

    monkeypatch.setattr(_us, "extract_cards_from_image", _fake_extract)
    return counter


# ── 1. Happy path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path_png_returns_candidates(client, monkeypatch):
    """100 KiB PNG → 200 + 3 candidates + 16-char screenshot_hash."""

    fake_cards = [
        CardCandidate(front=f"Q{i}?", back=f"A{i}.", concept_slug=None)
        for i in range(3)
    ]
    counter = _mock_extractor(monkeypatch, fake_cards, dropped=0)

    course_id = await _create_course(client)
    png_bytes = _make_png(100 * 1024)

    resp = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": course_id},
        files={"file": ("shot.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert len(payload["candidates"]) == 3
    assert all(c["front"].startswith("Q") for c in payload["candidates"])
    assert isinstance(payload["screenshot_hash"], str)
    assert len(payload["screenshot_hash"]) == 16
    assert payload["ungrounded_dropped_count"] == 0
    assert isinstance(payload["vision_latency_ms"], int)
    assert counter["calls"] == 1


# ── 2. Size cap ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_size_cap_6_mib_returns_413(client, monkeypatch):
    """6 MiB PNG body → 413 with the "too large" hint."""

    _mock_extractor(monkeypatch, [])

    course_id = await _create_course(client)
    big_png = _make_png(6 * 1024 * 1024)

    resp = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": course_id},
        files={"file": ("big.png", big_png, "image/png")},
    )
    assert resp.status_code == 413, resp.text
    # Detail is a nested {"detail": ..., "hint": ...} object per router contract.
    body = resp.json()
    detail = body.get("detail")
    if isinstance(detail, dict):
        assert "too large" in detail.get("detail", "").lower()
        assert "1600" in detail.get("hint", "")
    else:
        # Defensive: FastAPI may unwrap a dict-valued detail on some
        # versions; either way the text "too large" should be present.
        assert "too large" in str(body).lower()


# ── 3. MIME unsupported ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mime_unsupported_returns_415(client, monkeypatch):
    """Content-Type: application/pdf → 415."""

    _mock_extractor(monkeypatch, [])

    course_id = await _create_course(client)

    resp = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": course_id},
        files={"file": ("doc.pdf", b"%PDF-1.4\n", "application/pdf")},
    )
    assert resp.status_code == 415, resp.text
    assert "image/png" in resp.text


# ── 4. Rate limit ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_6th_in_60s_returns_429(client, monkeypatch):
    """5 POSTs within the window succeed, 6th returns 429.

    Uses a monkeypatched ``time.monotonic`` so the test runs in
    milliseconds rather than waiting a real 60 s.
    """

    fake_cards = [CardCandidate(front="Q?", back="A.")]
    _mock_extractor(monkeypatch, fake_cards)

    # Freeze the clock just inside the 60 s window — all 6 requests
    # will share the same timestamp so the oldest never falls off.
    import routers.upload_screenshot as _us

    fake_now = {"t": 1_000.0}
    monkeypatch.setattr(_us.time, "monotonic", lambda: fake_now["t"])

    course_id = await _create_course(client)

    # Each request must have a distinct body so the cache layer doesn't
    # short-circuit them — otherwise requests 2-6 would hit the TTL
    # cache BEFORE the rate-limit check and we'd never see the 429.
    # (The router does rate-limit first, then cache — but we keep bodies
    # distinct to make the test's intent unambiguous regardless of that
    # ordering.)
    for i in range(5):
        body = _make_png(2 * 1024 + i)
        resp = await client.post(
            "/api/content/upload/screenshot",
            data={"course_id": course_id},
            files={"file": (f"shot{i}.png", body, "image/png")},
        )
        assert resp.status_code == 200, f"req {i}: {resp.text}"

    resp6 = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": course_id},
        files={"file": ("shot6.png", _make_png(2 * 1024 + 99), "image/png")},
    )
    assert resp6.status_code == 429, resp6.text
    assert "slow down" in resp6.text.lower()

    # Slide the clock forward past the window — the bucket should refill.
    fake_now["t"] += _us._RATE_LIMIT_WINDOW_SEC + 1.0
    resp7 = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": course_id},
        files={"file": ("shot7.png", _make_png(2 * 1024 + 100), "image/png")},
    )
    assert resp7.status_code == 200, resp7.text


# ── 5. Idempotency cache ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotency_same_hash_cached(client, monkeypatch):
    """Same bytes posted twice → extractor invoked only once.

    Both responses share the same ``screenshot_hash`` and identical
    ``candidates`` list; the second one reports ``vision_latency_ms=0``
    (the cache-hit sentinel).
    """

    fake_cards = [
        CardCandidate(front="Why?", back="Because.", concept_slug="race-condition"),
        CardCandidate(front="What?", back="That.", concept_slug=None),
    ]
    counter = _mock_extractor(monkeypatch, fake_cards, dropped=0)

    course_id = await _create_course(client)
    png_bytes = _make_png(50 * 1024)

    first = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": course_id},
        files={"file": ("shot.png", png_bytes, "image/png")},
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": course_id},
        files={"file": ("shot.png", png_bytes, "image/png")},
    )
    assert second.status_code == 200, second.text

    assert counter["calls"] == 1, (
        f"expected 1 LLM call, cache miss fired {counter['calls']}"
    )
    assert first.json()["screenshot_hash"] == second.json()["screenshot_hash"]
    assert first.json()["candidates"] == second.json()["candidates"]
    # Cache-hit sentinel — latency reported as 0 on replay.
    assert second.json()["vision_latency_ms"] == 0


# ── 6. Course not found ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_course_not_found_returns_404(client, monkeypatch):
    """course_id not in DB → 404 from get_course_or_404."""

    _mock_extractor(monkeypatch, [])

    # Bootstrap the local user (single-user mode creates the row on
    # first auth dep invocation) so ``get_course_or_404`` isn't masked
    # by a 503 schema-missing path.
    await client.get("/api/health")

    missing_course_id = str(uuid.uuid4())
    png_bytes = _make_png(10 * 1024)

    resp = await client.post(
        "/api/content/upload/screenshot",
        data={"course_id": missing_course_id},
        files={"file": ("shot.png", png_bytes, "image/png")},
    )
    assert resp.status_code == 404, resp.text
