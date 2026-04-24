"""Integration tests for the ``/api/drills/*`` router (Phase 16c).

Covers the five endpoints plus the critic's route-ordering contract
(C8): ``/courses`` and ``/next`` MUST match literal segments rather than
being swallowed by the ``/{drill_id}`` UUID parameter. Reordering the
decorators in ``routers/drills.py`` breaks silently — a direct test
pins the contract.

Fixture harness is cloned from ``tests/routers/test_paths.py``: per-test
SQLite file, ``get_db`` override, ``database.async_session`` patch so
service-layer helpers that reach for the global session factory target
the test DB instead.
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
from models.drill import Drill, DrillAttempt, DrillCourse, DrillModule
from models.user import User


_HIDDEN_TESTS = (
    "from solution import add\n\ndef test_sum():\n    assert add(2, 3) == 5\n"
)
_CORRECT = "def add(a, b):\n    return a + b\n"
_WRONG = "def add(a, b):\n    return a - b\n"


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client_with_db():
    """Per-test ``AsyncClient`` + session factory bound to a fresh DB."""

    fd, db_path = tempfile.mkstemp(prefix="opentutor-drills-router-", suffix=".db")
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


async def _seed_user(session_factory) -> uuid.UUID:
    async with session_factory() as s:
        u = User(name="Owner")
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id


async def _seed_course(
    session_factory,
    *,
    slug: str = "cs50p",
    title: str = "CS50P",
    drills_per_module: int = 2,
    modules: int = 1,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Seed ``DrillCourse`` + ``DrillModule`` + ``Drill`` rows.

    Returns ``(course_id, [drill_id, ...])`` flattened across modules.
    """

    async with session_factory() as s:
        course = DrillCourse(slug=slug, title=title, source="test", version="v1.0.0")
        s.add(course)
        await s.commit()
        await s.refresh(course)

        drill_ids: list[uuid.UUID] = []
        for mi in range(modules):
            m = DrillModule(
                course_id=course.id,
                slug=f"m{mi + 1}",
                title=f"Module {mi + 1}",
                order_index=mi + 1,
            )
            s.add(m)
            await s.commit()
            await s.refresh(m)
            for di in range(drills_per_module):
                d = Drill(
                    module_id=m.id,
                    slug=f"m{mi + 1}-d{di + 1}",
                    order_index=di + 1,
                    title=f"Drill {mi + 1}.{di + 1}",
                    why_it_matters="practice",
                    starter_code="def add(a, b):\n    ...\n",
                    hidden_tests=_HIDDEN_TESTS,
                    hints=["Return a + b."],
                    skill_tags=["functions"],
                    source_citation="unit test",
                    time_budget_min=1,
                    difficulty_layer=1,
                )
                s.add(d)
                await s.commit()
                await s.refresh(d)
                drill_ids.append(d.id)
        return course.id, drill_ids


# ── Endpoint 1: GET /api/drills/courses ─────────────────────────────


@pytest.mark.asyncio
async def test_list_courses_returns_module_count(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)
    await _seed_course(factory, slug="cs50p", modules=2, drills_per_module=3)

    resp = await client.get("/api/drills/courses")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["slug"] == "cs50p"
    assert body[0]["module_count"] == 2


@pytest.mark.asyncio
async def test_list_courses_empty_when_no_seed(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)

    resp = await client.get("/api/drills/courses")

    assert resp.status_code == 200
    assert resp.json() == []


# ── Endpoint 2: GET /api/drills/courses/{slug} ──────────────────────


@pytest.mark.asyncio
async def test_get_course_toc_returns_modules_and_drills_ordered(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)
    await _seed_course(factory, slug="cs50p", modules=2, drills_per_module=2)

    resp = await client.get("/api/drills/courses/cs50p")

    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "cs50p"
    assert body["module_count"] == 2
    assert len(body["modules"]) == 2
    assert body["modules"][0]["order_index"] == 1
    assert body["modules"][1]["order_index"] == 2
    # Each module has its drills inline, ordered
    assert [d["order_index"] for d in body["modules"][0]["drills"]] == [1, 2]
    # hidden_tests MUST NOT appear in the wire payload
    for module in body["modules"]:
        for drill in module["drills"]:
            assert "hidden_tests" not in drill


@pytest.mark.asyncio
async def test_get_course_toc_404_on_unknown_slug(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)

    resp = await client.get("/api/drills/courses/nope")

    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["error"] == "course_not_found"


# ── Endpoint 3: GET /api/drills/next ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_next_drill_returns_first_unpassed(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)
    _, drill_ids = await _seed_course(factory, modules=1, drills_per_module=2)

    resp = await client.get("/api/drills/next?course_slug=cs50p")

    assert resp.status_code == 200
    body = resp.json()
    # The first drill has order_index 1
    assert body["order_index"] == 1
    assert body["id"] == str(drill_ids[0])


@pytest.mark.asyncio
async def test_get_next_drill_204_when_course_complete(client_with_db):
    client, factory = client_with_db
    user_id = await _seed_user(factory)
    _, drill_ids = await _seed_course(factory, modules=1, drills_per_module=1)

    # Seed a passing attempt for the only drill
    async with factory() as s:
        s.add(
            DrillAttempt(
                user_id=user_id,
                drill_id=drill_ids[0],
                passed=True,
                submitted_code=_CORRECT,
            )
        )
        await s.commit()

    resp = await client.get("/api/drills/next?course_slug=cs50p")

    assert resp.status_code == 204
    # 204 must have an empty body per RFC
    assert resp.content in (b"", b"null")


# ── Critic C8: route-ordering regression ────────────────────────────


@pytest.mark.asyncio
async def test_next_endpoint_literal_not_uuid_parsed(client_with_db):
    """Verify ``/next`` matches as a literal segment, not as ``/{drill_id}``.

    If the router decorators get reordered so ``/{drill_id}`` is
    registered first, FastAPI would try to parse ``"next"`` as a UUID
    and return 422 (validation error). The current ordering returns
    a normal 200/204 instead.
    """

    client, factory = client_with_db
    await _seed_user(factory)
    await _seed_course(factory)

    resp = await client.get("/api/drills/next?course_slug=cs50p")

    # The bug shape we're guarding against: ``422 {loc: ["path", "drill_id"]}``.
    assert resp.status_code != 422
    assert resp.status_code in (200, 204)


@pytest.mark.asyncio
async def test_courses_list_literal_not_uuid_parsed(client_with_db):
    """``/courses`` MUST match as a literal segment, not ``/{drill_id}``."""

    client, factory = client_with_db
    await _seed_user(factory)

    resp = await client.get("/api/drills/courses")

    assert resp.status_code != 422
    assert resp.status_code == 200


# ── Endpoint 4: GET /api/drills/{drill_id} ──────────────────────────


@pytest.mark.asyncio
async def test_get_drill_returns_drill_without_hidden_tests(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)
    _, drill_ids = await _seed_course(factory, modules=1, drills_per_module=1)

    resp = await client.get(f"/api/drills/{drill_ids[0]}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(drill_ids[0])
    assert "hidden_tests" not in body
    assert body["starter_code"].startswith("def add")


@pytest.mark.asyncio
async def test_get_drill_404_on_unknown_uuid(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)

    resp = await client.get(f"/api/drills/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "drill_not_found"


# ── Endpoint 5: POST /api/drills/{drill_id}/submit ──────────────────


@pytest.mark.asyncio
async def test_post_submit_pass_returns_next_drill(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)
    _, drill_ids = await _seed_course(factory, modules=1, drills_per_module=2)

    resp = await client.post(
        f"/api/drills/{drill_ids[0]}/submit",
        json={"submitted_code": _CORRECT},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is True
    assert body["feedback"] == "Чисто! Тест пройдено."
    assert body["next_drill_id"] == str(drill_ids[1])


@pytest.mark.asyncio
async def test_post_submit_fail_returns_null_next(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)
    _, drill_ids = await _seed_course(factory, modules=1, drills_per_module=2)

    resp = await client.post(
        f"/api/drills/{drill_ids[0]}/submit",
        json={"submitted_code": _WRONG},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["passed"] is False
    assert body["next_drill_id"] is None


@pytest.mark.asyncio
async def test_post_submit_404_on_unknown_drill(client_with_db):
    client, factory = client_with_db
    await _seed_user(factory)

    resp = await client.post(
        f"/api/drills/{uuid.uuid4()}/submit",
        json={"submitted_code": _CORRECT},
    )

    assert resp.status_code == 404
    assert resp.json()["detail"]["error"] == "drill_not_found"
