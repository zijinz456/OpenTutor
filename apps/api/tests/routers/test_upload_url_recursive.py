"""Integration tests for ``POST /api/content/upload/url/recursive`` (§14.5 v2.5 T3).

Five criteria per plan:

1. Crawl success → one ``IngestionJob`` per ``status="ok"`` page; response
   carries matching ``job_ids`` and ``pages_crawled``.
2. Mixed crawler statuses aggregate into the right response buckets
   (``skip_robots``/``skip_origin``/``fetch_fail``/``ok``).
3. Two concurrent requests for the same ``course_id`` → second request
   returns 409 via the module-level ``_ACTIVE_CRAWLS`` guard.
4. Syntactically-bad URL (``"not a url"``) → 400.
5. ``max_depth=5`` (outside the ``Literal[1,2,3]`` contract) → 422 via
   pydantic's request validator.

The crawler is mocked by monkeypatching ``crawl_urls`` at the router
module's binding site so neither httpx nor real robots.txt is consulted.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import uuid
from collections.abc import AsyncIterator

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
from services.crawler.recursive_crawler import CrawledPage


# ── Per-test client with isolated SQLite (same shape as test_upload_coursera) ──


@pytest_asyncio.fixture
async def client(monkeypatch):
    """Per-test ``AsyncClient`` with an isolated SQLite DB."""
    # Stub libmagic — Windows segfault, and the recursive pipeline always
    # gets text/markdown blobs, so the real detector adds nothing.
    import services.ingestion.pipeline as _pipe_mod

    monkeypatch.setattr(_pipe_mod, "detect_mime_type", lambda *a, **kw: "text/markdown")

    fd, db_path = tempfile.mkstemp(prefix="opentutor-recursive-", suffix=".db")
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

    import routers.upload_url_recursive as _uur

    monkeypatch.setattr(_uur, "async_session", test_session_factory, raising=True)

    # Prevent real syllabus builder runs in CI.
    async def _noop_syllabus(course_id, delay=0):  # noqa: ARG001
        return None

    monkeypatch.setattr(_uur, "_post_recursive_syllabus", _noop_syllabus)

    # Upload dir in a temp location so we don't pollute settings.upload_dir.
    tmp_upload = tempfile.mkdtemp(prefix="opentutor-recursive-upload-")
    from config import settings as _settings

    monkeypatch.setattr(_settings, "upload_dir", tmp_upload, raising=False)

    # Ensure the module-level crawl set is empty at test entry — a previous
    # test that crashed mid-crawl could otherwise leave state behind.
    _uur._ACTIVE_CRAWLS.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.pop(get_db, None)
    database_module.async_session = original_async_session
    if hasattr(app.state, "test_session_factory"):
        delattr(app.state, "test_session_factory")
    _uur._ACTIVE_CRAWLS.clear()
    await test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


async def _create_course(client: AsyncClient, name: str = "Recursive Course") -> str:
    resp = await client.post(
        "/api/courses/", json={"name": name, "description": "test"}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _mk_crawl_mock(pages: list[CrawledPage]):
    """Return a callable that mimics ``crawl_urls`` by yielding ``pages``.

    Matches ``crawl_urls``'s signature loosely — the router passes several
    kwargs we deliberately ignore in tests.
    """

    async def _fake_crawl(*args, **kwargs) -> AsyncIterator[CrawledPage]:  # noqa: ARG001
        for page in pages:
            # Yield within an await so the coroutine actually suspends —
            # matches the real crawler's scheduling behavior.
            await asyncio.sleep(0)
            yield page

    return _fake_crawl


# ── 1. Happy path — 3 ok pages create 3 jobs ───────────────────────────


@pytest.mark.asyncio
async def test_post_recursive_crawls_and_creates_jobs(client, monkeypatch):
    """3 ``ok`` pages → 3 IngestionJob rows, response job_ids len 3."""
    pages = [
        CrawledPage(
            url=f"http://example.com/p{i}",
            depth=0 if i == 1 else 1,
            html=f"<html><body><h1>Page {i}</h1><p>body {i}</p></body></html>",
            status="ok",
        )
        for i in range(1, 4)
    ]

    import routers.upload_url_recursive as _uur

    monkeypatch.setattr(_uur, "crawl_urls", _mk_crawl_mock(pages))

    course_id = await _create_course(client)
    resp = await client.post(
        "/api/content/upload/url/recursive",
        json={
            "url": "http://example.com/p1",
            "course_id": course_id,
            "max_depth": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["course_id"] == course_id
    assert payload["pages_crawled"] == 3
    assert payload["pages_skipped_robots"] == 0
    assert payload["pages_skipped_origin"] == 0
    assert payload["pages_skipped_dedup"] == 0
    assert payload["pages_fetch_failed"] == 0
    assert len(payload["job_ids"]) == 3

    # Verify DB rows exist with source_type="url_recursive".
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
    assert all(r.source_type == "url_recursive" for r in rows)
    # Every job should have recorded the originating crawl URL.
    crawled_urls = {r.url for r in rows}
    assert crawled_urls == {
        "http://example.com/p1",
        "http://example.com/p2",
        "http://example.com/p3",
    }


# ── 2. Status bucket aggregation ───────────────────────────────────────


@pytest.mark.asyncio
async def test_post_recursive_aggregates_skip_statuses(client, monkeypatch):
    """Mixed crawler statuses populate every response bucket correctly."""
    pages = [
        CrawledPage(
            url="http://example.com/ok1",
            depth=0,
            html="<p>ok1</p>",
            status="ok",
        ),
        CrawledPage(
            url="http://example.com/ok2",
            depth=1,
            html="<p>ok2</p>",
            status="ok",
        ),
        CrawledPage(
            url="http://example.com/robots-blocked",
            depth=1,
            html=None,
            status="skip_robots",
        ),
        CrawledPage(
            url="https://external.com/page",
            depth=1,
            html=None,
            status="skip_origin",
        ),
        CrawledPage(
            url="http://example.com/boom",
            depth=1,
            html=None,
            status="fetch_fail",
        ),
    ]

    import routers.upload_url_recursive as _uur

    monkeypatch.setattr(_uur, "crawl_urls", _mk_crawl_mock(pages))

    course_id = await _create_course(client)
    resp = await client.post(
        "/api/content/upload/url/recursive",
        json={
            "url": "http://example.com/ok1",
            "course_id": course_id,
            "max_depth": 2,
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()

    assert payload["pages_crawled"] == 2
    assert payload["pages_skipped_robots"] == 1
    assert payload["pages_skipped_origin"] == 1
    assert payload["pages_skipped_dedup"] == 0
    assert payload["pages_fetch_failed"] == 1
    assert len(payload["job_ids"]) == 2


# ── 3. Concurrency guard on course_id ──────────────────────────────────


@pytest.mark.asyncio
async def test_post_recursive_concurrent_same_course_returns_409(client, monkeypatch):
    """Two concurrent requests for the same course_id → second one is 409."""

    # Build a crawler that actually suspends long enough for the second
    # request to observe the first in ``_ACTIVE_CRAWLS``. Without the gate
    # the two crawls would race to completion and both would be 200.
    async def _slow_crawl(*args, **kwargs) -> AsyncIterator[CrawledPage]:  # noqa: ARG001
        # One ok page, but only after a few scheduler ticks so the second
        # request definitely reaches the guard while we're still inside.
        for _ in range(10):
            await asyncio.sleep(0.01)
        yield CrawledPage(
            url="http://example.com/slow",
            depth=0,
            html="<p>slow</p>",
            status="ok",
        )

    import routers.upload_url_recursive as _uur

    monkeypatch.setattr(_uur, "crawl_urls", _slow_crawl)

    course_id = await _create_course(client)
    body = {
        "url": "http://example.com/slow",
        "course_id": course_id,
        "max_depth": 1,
    }

    # Fire both requests before awaiting either — they overlap in the event
    # loop, so the second one hits the guard mid-way through the first.
    task1 = asyncio.create_task(
        client.post("/api/content/upload/url/recursive", json=body)
    )
    # A tiny pre-yield so task1 gets past ``_ACTIVE_CRAWLS.add`` before
    # task2 starts — without this, which request "wins" the guard is
    # scheduler-dependent and the test becomes flaky.
    await asyncio.sleep(0.02)
    task2 = asyncio.create_task(
        client.post("/api/content/upload/url/recursive", json=body)
    )

    resp1, resp2 = await asyncio.gather(task1, task2)

    statuses = sorted([resp1.status_code, resp2.status_code])
    assert statuses == [200, 409], (
        f"expected one 200 and one 409, got {resp1.status_code}/{resp2.status_code}: "
        f"{resp1.text} | {resp2.text}"
    )
    # The 409 should carry the structured detail for the UI layer.
    loser = resp1 if resp1.status_code == 409 else resp2
    body_err = loser.json()
    # ``AppError`` serializer uses ``message``; we accept either to stay
    # resilient to handler changes.
    detail = body_err.get("message") or body_err.get("detail", "")
    assert "already in progress" in detail.lower()


# ── 4. Invalid URL → 400 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_recursive_invalid_url_returns_400(client, monkeypatch):
    """Syntactically-bad URL → HTTP 400 from the router's own gate."""
    # No need to mock the crawler — the gate runs first.
    import routers.upload_url_recursive as _uur

    monkeypatch.setattr(_uur, "crawl_urls", _mk_crawl_mock([]))

    course_id = await _create_course(client)
    resp = await client.post(
        "/api/content/upload/url/recursive",
        json={
            "url": "not a url",
            "course_id": course_id,
            "max_depth": 1,
        },
    )
    assert resp.status_code == 400, resp.text


# ── 5. Out-of-range max_depth → 422 ───────────────────────────────────


@pytest.mark.asyncio
async def test_post_recursive_bad_depth_returns_422(client, monkeypatch):
    """``max_depth=5`` is not in ``Literal[1,2,3]`` → pydantic 422."""
    import routers.upload_url_recursive as _uur

    monkeypatch.setattr(_uur, "crawl_urls", _mk_crawl_mock([]))

    course_id = await _create_course(client)
    resp = await client.post(
        "/api/content/upload/url/recursive",
        json={
            "url": "http://example.com/seed",
            "course_id": course_id,
            "max_depth": 5,
        },
    )
    assert resp.status_code == 422, resp.text
