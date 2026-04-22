"""Integration tests for ``POST /upload/coursera`` (Phase 14 T3+T5).

Covers the plan's five criteria:

1. Per-pair job creation — 3-lecture ZIP → 3 ``IngestionJob`` rows tagged
   ``source_type="coursera"``.
2. Syllabus batch gate — 5-lecture ZIP triggers ``build_syllabus`` exactly
   ONCE across the whole batch (not N times).
3. Idempotency — re-posting the same ZIP returns ``status="already_imported"``
   with an empty ``job_ids`` list.
4. Oversized / malformed ZIP — path-traversal entry is rejected with HTTP
   422 (ValidationError) and the ``hint`` text is surfaced.
5. Unknown course_id — HTTP 404 (NotFoundError).
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import uuid
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from models.ingestion import IngestionJob


# ── ZIP fixture helpers ─────────────────────────────────────────────────

_SAMPLE_VTT = (
    b"WEBVTT\n\n"
    b"00:00:01.000 --> 00:00:05.000\n"
    b"Welcome to the lecture on {topic}.\n"
    b"\n"
    b"00:00:06.000 --> 00:00:10.000\n"
    b"Today we discuss {topic} in depth with examples.\n"
)

# A tiny but syntactically real PDF — pypdf opens it and returns no text.
# That's fine: merge_lecture_markdown still emits a Transcript section from
# the VTT and the synthetic .md ends up as a "notes" category via text_fallback.
_MINIMAL_PDF = (
    b"%PDF-1.1\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n0000000000 65535 f \n"
    b"0000000009 00000 n \n0000000053 00000 n \n0000000093 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n147\n%%EOF\n"
)


def _make_lectures_zip(n: int, *, pdf_for: set[int] | None = None) -> bytes:
    """Build an in-memory ZIP with ``n`` lectures under ``Week-1/``.

    Each lecture always has a VTT. When ``pdf_for`` is given, only those
    lecture indices also get a PDF (otherwise every lecture gets one).
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for idx in range(1, n + 1):
            name = f"L{idx}-Topic{idx}"
            zf.writestr(
                f"Week-1/{name}.vtt",
                _SAMPLE_VTT.replace(b"{topic}", f"topic {idx}".encode()),
            )
            if pdf_for is None or idx in pdf_for:
                zf.writestr(f"Week-1/{name}.pdf", _MINIMAL_PDF)
    return buf.getvalue()


def _make_multiweek_zip(weeks: dict[int, int]) -> bytes:
    """Build a ZIP with ``{week_index: lecture_count}`` lectures per week.

    Each lecture gets both a VTT and a PDF. Used by the T6 ADHD clamp
    tests to synthesize over-sized courses that span multiple weeks.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        for week, count in weeks.items():
            for idx in range(1, count + 1):
                name = f"L{idx}-Topic{idx}"
                zf.writestr(
                    f"Week-{week}/{name}.vtt",
                    _SAMPLE_VTT.replace(b"{topic}", f"w{week}l{idx}".encode()),
                )
                zf.writestr(f"Week-{week}/{name}.pdf", _MINIMAL_PDF)
    return buf.getvalue()


# ── Per-test client with isolated SQLite ───────────────────────────────


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Per-test ``AsyncClient`` with an isolated SQLite DB.

    Mirrors the fixture in ``tests/test_api_integration.py`` so tests here
    run the real router + pipeline without touching a shared database.
    """
    # libmagic on Windows can segfault when first imported via the pipeline's
    # ``detect_mime_type``. Stub it here — for the synthetic ``.coursera.md``
    # files we know the MIME is ``text/markdown`` anyway.
    import services.ingestion.pipeline as _pipe_mod

    monkeypatch.setattr(_pipe_mod, "detect_mime_type", lambda *a, **kw: "text/markdown")

    fd, db_path = tempfile.mkstemp(prefix="opentutor-coursera-", suffix=".db")
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

    # Route router_coursera's direct import of ``async_session`` at the same time.
    import routers.upload_coursera as _uc

    monkeypatch.setattr(_uc, "async_session", test_session_factory, raising=True)

    # Route uploads to a throwaway dir to avoid polluting settings.upload_dir.
    tmp_upload = tempfile.mkdtemp(prefix="opentutor-coursera-upload-")
    from config import settings as _settings

    monkeypatch.setattr(_settings, "upload_dir", tmp_upload, raising=False)

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


async def _create_course(client: AsyncClient, name: str = "Coursera Course") -> str:
    resp = await client.post(
        "/api/courses/", json={"name": name, "description": "test"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ── 1. Per-pair job creation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_coursera_creates_jobs_per_pair(client, monkeypatch):
    """3-lecture ZIP → 3 IngestionJob rows with source_type='coursera'."""
    # Avoid firing the real syllabus builder during this test (no LLM in CI).
    import routers.upload_coursera as _uc

    async def _noop_syllabus(course_id, delay=0, roadmap_scope=None):  # noqa: ARG001
        return None

    monkeypatch.setattr(_uc, "_post_coursera_syllabus", _noop_syllabus)

    course_id = await _create_course(client)
    zip_bytes = _make_lectures_zip(3)

    resp = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": course_id},
        files={"file": ("lectures.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["status"] == "created"
    assert payload["lectures_total"] == 3
    assert payload["lectures_paired"] == 3
    assert payload["lectures_vtt_only"] == 0
    assert payload["lectures_pdf_only"] == 0
    assert len(payload["job_ids"]) == 3

    # Verify DB rows exist and are tagged coursera.
    async with app.state.test_session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(IngestionJob).where(
                        IngestionJob.course_id == uuid.UUID(course_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 3
    assert all(r.source_type == "coursera" for r in rows)
    # Each job was actually processed: content_category is non-null.
    assert all(r.content_category for r in rows)


# ── 2. Syllabus batch gate — exactly one call ───────────────────────────


@pytest.mark.asyncio
async def test_post_coursera_syllabus_called_once_not_per_job(client, monkeypatch):
    """5-lecture ZIP → build_syllabus invoked exactly once for the batch."""
    import routers.upload_coursera as _uc

    call_count = {"n": 0}

    async def _counting_syllabus(course_id, delay=0, roadmap_scope=None):  # noqa: ARG001
        call_count["n"] += 1

    monkeypatch.setattr(_uc, "_post_coursera_syllabus", _counting_syllabus)

    course_id = await _create_course(client)
    zip_bytes = _make_lectures_zip(5)

    resp = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": course_id},
        files={"file": ("lectures.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["job_ids"]) == 5

    # Let the scheduled background task run.
    await asyncio.sleep(0.1)

    assert call_count["n"] == 1, (
        f"expected build_syllabus trigger to fire exactly once, got {call_count['n']}"
    )


# ── 3. Idempotency ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_coursera_idempotency_same_zip_returns_already_imported(
    client, monkeypatch
):
    """Re-posting the same ZIP returns status='already_imported' with no new jobs."""
    import routers.upload_coursera as _uc

    async def _noop_syllabus(course_id, delay=0, roadmap_scope=None):  # noqa: ARG001
        return None

    monkeypatch.setattr(_uc, "_post_coursera_syllabus", _noop_syllabus)

    course_id = await _create_course(client)
    zip_bytes = _make_lectures_zip(2)

    first = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": course_id},
        files={"file": ("lectures.zip", zip_bytes, "application/zip")},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "created"
    assert len(first.json()["job_ids"]) == 2

    second = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": course_id},
        files={"file": ("lectures.zip", zip_bytes, "application/zip")},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["status"] == "already_imported"
    assert body["job_ids"] == []
    assert body["lectures_total"] == 2


# ── 4. Malformed ZIP rejected with a structured error ──────────────────


@pytest.mark.asyncio
async def test_post_coursera_rejects_oversized(client, monkeypatch):
    """Path-traversal entry → HTTP 422 (ValidationError) with adapter hint surfaced."""
    import routers.upload_coursera as _uc

    async def _noop_syllabus(course_id, delay=0, roadmap_scope=None):  # noqa: ARG001
        return None

    monkeypatch.setattr(_uc, "_post_coursera_syllabus", _noop_syllabus)

    course_id = await _create_course(client)

    # Use the same malicious-path fixture shape as the T1 adapter tests.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("Week-1/L1-Intro.vtt", b"WEBVTT\n")
        zf.writestr("../etc/passwd", b"root:x:0:0")
    zip_bytes = buf.getvalue()

    resp = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": course_id},
        files={"file": ("bad.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json().get("message", "").lower()
    assert "invalid" in detail or "traversal" in detail or "size cap" in detail


# ── 5. Unknown course_id → 404 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_coursera_bad_course_id_404(client, monkeypatch):
    """course_id not in DB → HTTP 404 from get_course_or_404."""
    import routers.upload_coursera as _uc

    async def _noop_syllabus(course_id, delay=0, roadmap_scope=None):  # noqa: ARG001
        return None

    monkeypatch.setattr(_uc, "_post_coursera_syllabus", _noop_syllabus)

    # Bootstrap the local user by hitting a cheap endpoint first so that
    # get_course_or_404 isn't masked by an earlier User-creation 503 path.
    await client.get("/api/health")

    missing_course_id = str(uuid.uuid4())
    zip_bytes = _make_lectures_zip(1)

    resp = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": missing_course_id},
        files={"file": ("lectures.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 404, resp.text


# ── 6. T6 ADHD clamp — > 20 lectures roadmaps only the first week ──────


@pytest.mark.asyncio
async def test_post_coursera_25_lectures_clamps_to_first_week(client, monkeypatch):
    """25-lecture ZIP (W1/10 + W2/10 + W3/5) → roadmap scoped to Week-1 only.

    Assertions:
    - ``build_syllabus`` invoked via ``_post_coursera_syllabus`` with a
      ``roadmap_scope`` kwarg whose ``week_prefix_filter`` ends in ``Week-1/``.
    - Persisted course metadata carries ``locked_weeks == [2, 3]``.
    """
    import routers.upload_coursera as _uc

    captured: dict[str, object] = {}

    async def _spy_syllabus(course_id, delay=0, roadmap_scope=None):  # noqa: ARG001
        captured["course_id"] = course_id
        captured["roadmap_scope"] = roadmap_scope

    monkeypatch.setattr(_uc, "_post_coursera_syllabus", _spy_syllabus)

    course_id = await _create_course(client)
    zip_bytes = _make_multiweek_zip({1: 10, 2: 10, 3: 5})

    resp = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": course_id},
        files={"file": ("bigcourse.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["lectures_total"] == 25
    assert len(payload["job_ids"]) == 25

    # Let the scheduled background task fire so `captured` populates.
    await asyncio.sleep(0.1)

    scope = captured.get("roadmap_scope")
    assert isinstance(scope, dict), f"expected roadmap_scope dict, got {scope!r}"
    prefix = scope.get("week_prefix_filter")
    assert isinstance(prefix, str) and prefix.endswith("Week-1/"), (
        f"expected week_prefix_filter ending 'Week-1/', got {prefix!r}"
    )

    # DB: course.metadata_["locked_weeks"] populated with the non-first weeks.
    from models.course import Course

    async with app.state.test_session_factory() as session:
        row = (
            await session.execute(
                select(Course).where(Course.id == uuid.UUID(course_id))
            )
        ).scalar_one()
        await session.refresh(row)
        locked = (row.metadata_ or {}).get("locked_weeks")
    assert locked == [2, 3], f"expected locked_weeks=[2,3], got {locked!r}"


@pytest.mark.asyncio
async def test_post_coursera_10_lectures_no_clamp(client, monkeypatch):
    """Under-threshold ZIP (10 lectures in Week-1) → no clamp, empty locked list."""
    import routers.upload_coursera as _uc

    captured: dict[str, object] = {}

    async def _spy_syllabus(course_id, delay=0, roadmap_scope=None):  # noqa: ARG001
        captured["course_id"] = course_id
        captured["roadmap_scope"] = roadmap_scope
        captured["called"] = True

    monkeypatch.setattr(_uc, "_post_coursera_syllabus", _spy_syllabus)

    course_id = await _create_course(client)
    zip_bytes = _make_lectures_zip(10)

    resp = await client.post(
        "/api/content/upload/coursera",
        data={"course_id": course_id},
        files={"file": ("small.zip", zip_bytes, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lectures_total"] == 10

    await asyncio.sleep(0.1)

    assert captured.get("called") is True
    got_scope = captured.get("roadmap_scope")
    assert got_scope is None, (
        f"expected roadmap_scope=None under threshold, got {got_scope!r}"
    )

    from models.course import Course

    async with app.state.test_session_factory() as session:
        row = (
            await session.execute(
                select(Course).where(Course.id == uuid.UUID(course_id))
            )
        ).scalar_one()
        await session.refresh(row)
        locked = (row.metadata_ or {}).get("locked_weeks")
    assert locked == [], (
        f"expected empty locked_weeks list (not None) under threshold, got {locked!r}"
    )
