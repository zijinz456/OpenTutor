"""Integration tests for the ``/api/paths/*`` router (Phase 16a T3).

Covers the eight router-level acceptance criteria:

1. ``test_get_paths_returns_python_and_hacking_tracks`` — Python and
   Hacking paths both surface with distinct ``track_id`` values.
2. ``test_get_paths_progress_counts_completed_tasks`` — a single
   correct answer bumps ``task_complete`` but leaves ``room_complete``
   at 0 while other tasks remain unanswered.
3. ``test_get_paths_room_complete_when_all_tasks_correct`` — every
   task green → ``room_complete`` increments.
4. ``test_get_path_detail_returns_rooms_ordered`` — rooms come back in
   ``room_order`` ascending even when inserted out of order.
5. ``test_get_path_detail_404_on_missing_slug`` — unknown slug → 404.
6. ``test_get_room_detail_includes_tasks_ordered`` — tasks sort by
   ``task_order`` ascending with NULLs last; ``correct_answer`` is
   absent from the payload.
7. ``test_get_room_detail_task_is_complete_flag`` — one correct answer
   flips the corresponding ``is_complete``.
8. ``test_get_orphans_returns_count_and_sample`` — 15 orphan cards →
   ``count=15`` and exactly 10 sample rows.

Fixture harness mirrors ``tests/routers/test_freeze.py`` — per-test
SQLite file, ``get_db`` override, ``database.async_session`` patch so
helpers that import the global session factory still target the test
DB.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import tempfile
import uuid
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem, PracticeResult
from models.user import User


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client_with_db():
    """Per-test ``AsyncClient`` + session factory bound to a fresh DB."""

    fd, db_path = tempfile.mkstemp(prefix="opentutor-paths-router-", suffix=".db")
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
    """Create the single local user the auth dependency expects."""

    async with session_factory() as session:
        user = User(name="Owner")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user.id


async def _seed_course(session_factory, *, user_id: uuid.UUID) -> uuid.UUID:
    async with session_factory() as session:
        course = Course(name="Python", description="t", user_id=user_id)
        session.add(course)
        await session.commit()
        await session.refresh(course)
        return course.id


async def _seed_path(
    session_factory,
    *,
    slug: str,
    title: str = "Path",
    difficulty: str = "beginner",
    track_id: str | None = None,
    description: Optional[str] = None,
    room_count_target: int = 0,
) -> uuid.UUID:
    path_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            LearningPath(
                id=path_id,
                slug=slug,
                title=title,
                difficulty=difficulty,
                track_id=track_id or slug.replace("-", "_"),
                description=description,
                room_count_target=room_count_target,
            )
        )
        await session.commit()
    return path_id


async def _seed_room(
    session_factory,
    *,
    path_id: uuid.UUID,
    slug: str,
    title: str = "Room",
    room_order: int = 0,
    intro_excerpt: Optional[str] = None,
    outcome: str = "Complete this mission",
    difficulty: int = 2,
    eta_minutes: int = 15,
    module_label: str = "",
) -> uuid.UUID:
    room_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug=slug,
                title=title,
                room_order=room_order,
                intro_excerpt=intro_excerpt,
                outcome=outcome,
                difficulty=difficulty,
                eta_minutes=eta_minutes,
                module_label=module_label,
            )
        )
        await session.commit()
    return room_id


async def _seed_problem(
    session_factory,
    *,
    course_id: uuid.UUID,
    room_id: Optional[uuid.UUID] = None,
    task_order: Optional[int] = None,
    question: str = "Q?",
    question_type: str = "mc",
    correct_answer: str = "a",
) -> uuid.UUID:
    problem_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            PracticeProblem(
                id=problem_id,
                course_id=course_id,
                question_type=question_type,
                question=question,
                options={"choices": ["a", "b"]},
                correct_answer=correct_answer,
                path_room_id=room_id,
                task_order=task_order,
            )
        )
        await session.commit()
    return problem_id


async def _seed_correct_result(
    session_factory,
    *,
    user_id: uuid.UUID,
    problem_id: uuid.UUID,
    answered_at: datetime | None = None,
) -> None:
    async with session_factory() as session:
        session.add(
            PracticeResult(
                problem_id=problem_id,
                user_id=user_id,
                user_answer="a",
                is_correct=True,
                answered_at=answered_at or datetime.now(timezone.utc),
            )
        )
        await session.commit()


# ── 1. GET /api/paths — all seeded paths surface ────────────────────


@pytest.mark.asyncio
async def test_get_paths_returns_python_and_hacking_tracks(client_with_db) -> None:
    """Python and Hacking paths both surface with distinct track IDs."""

    ac, factory = client_with_db
    await _seed_user(factory)
    python_path = await _seed_path(
        factory,
        slug="python-fundamentals",
        title="Python Fundamentals",
        track_id="python_fundamentals",
    )
    hacking_path = await _seed_path(
        factory,
        slug="hacking-foundations",
        title="Hacking Foundations",
        track_id="hacking_foundations",
    )
    await _seed_room(factory, path_id=python_path, slug="intro", room_order=0)
    await _seed_room(factory, path_id=python_path, slug="loops", room_order=1)
    await _seed_room(factory, path_id=hacking_path, slug="recon", room_order=0)
    await _seed_room(factory, path_id=hacking_path, slug="juice-shop", room_order=1)

    resp = await ac.get("/api/paths")
    assert resp.status_code == 200, resp.text
    by_slug = {path["slug"]: path for path in resp.json()["paths"]}

    assert set(by_slug) == {"python-fundamentals", "hacking-foundations"}
    assert by_slug["python-fundamentals"]["track_id"] == "python_fundamentals"
    assert by_slug["hacking-foundations"]["track_id"] == "hacking_foundations"
    assert by_slug["python-fundamentals"]["room_total"] == 2
    assert by_slug["hacking-foundations"]["room_total"] == 2
    assert by_slug["python-fundamentals"]["room_complete"] == 0
    assert by_slug["hacking-foundations"]["room_complete"] == 0
    assert by_slug["python-fundamentals"]["task_total"] == 0
    assert by_slug["hacking-foundations"]["task_total"] == 0


# ── 2. GET /api/paths — 1/3 correct → task_complete=1, room_complete=0 ─


@pytest.mark.asyncio
async def test_get_paths_progress_counts_completed_tasks(client_with_db) -> None:
    """One correct answer out of three → task_complete=1 but room not done."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(factory, slug="python-fundamentals")
    room_id = await _seed_room(factory, path_id=path_id, slug="intro", room_order=0)
    problems = [
        await _seed_problem(factory, course_id=course_id, room_id=room_id, task_order=i)
        for i in range(3)
    ]
    # Answer only the first correctly.
    await _seed_correct_result(factory, user_id=user_id, problem_id=problems[0])

    resp = await ac.get("/api/paths")
    assert resp.status_code == 200, resp.text
    summary = next(
        p for p in resp.json()["paths"] if p["slug"] == "python-fundamentals"
    )
    assert summary["task_total"] == 3
    assert summary["task_complete"] == 1
    assert summary["room_complete"] == 0  # not every task green yet
    assert summary["room_total"] == 1


# ── 3. GET /api/paths — 2/2 correct → room_complete=1 ──────────────


@pytest.mark.asyncio
async def test_get_paths_room_complete_when_all_tasks_correct(client_with_db) -> None:
    """Every task in a single-room path green → room_complete=1."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(factory, slug="python-fundamentals")
    room_id = await _seed_room(factory, path_id=path_id, slug="intro", room_order=0)
    p1 = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=0
    )
    p2 = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=1
    )
    await _seed_correct_result(factory, user_id=user_id, problem_id=p1)
    await _seed_correct_result(factory, user_id=user_id, problem_id=p2)

    resp = await ac.get("/api/paths")
    assert resp.status_code == 200, resp.text
    summary = next(
        p for p in resp.json()["paths"] if p["slug"] == "python-fundamentals"
    )
    assert summary["task_total"] == 2
    assert summary["task_complete"] == 2
    assert summary["room_complete"] == 1
    assert summary["room_total"] == 1


# ── 4. GET /api/paths/{slug} — rooms ordered by room_order ─────────


@pytest.mark.asyncio
async def test_get_path_detail_returns_rooms_ordered(client_with_db) -> None:
    """Rooms inserted [2, 0, 1] → response rooms ordered [0, 1, 2]."""

    ac, factory = client_with_db
    await _seed_user(factory)
    path_id = await _seed_path(factory, slug="python-fundamentals")
    # Insert out of order to prove the ORDER BY is not a lucky accident.
    await _seed_room(factory, path_id=path_id, slug="third", room_order=2)
    await _seed_room(factory, path_id=path_id, slug="first", room_order=0)
    await _seed_room(factory, path_id=path_id, slug="second", room_order=1)

    resp = await ac.get("/api/paths/python-fundamentals")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [r["room_order"] for r in body["rooms"]] == [0, 1, 2]
    assert [r["slug"] for r in body["rooms"]] == ["first", "second", "third"]
    assert body["rooms"][0]["outcome"] == "Complete this mission"
    assert body["rooms"][0]["difficulty"] == 2
    assert body["rooms"][0]["eta_minutes"] == 15
    assert body["rooms"][0]["module_label"] == ""


# ── 5. GET /api/paths/{slug} — 404 on missing slug ─────────────────


@pytest.mark.asyncio
async def test_get_path_detail_404_on_missing_slug(client_with_db) -> None:
    ac, factory = client_with_db
    await _seed_user(factory)

    resp = await ac.get("/api/paths/does-not-exist")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error"] == "path_not_found"


# ── 6. GET /api/paths/{slug}/rooms/{room_id} — tasks ordered, no answer ─


@pytest.mark.asyncio
async def test_get_room_detail_includes_tasks_ordered(client_with_db) -> None:
    """Task_orders [1, 0, None, 2, None] → response in [0,1,2, None, None]."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(factory, slug="python-fundamentals")
    room_id = await _seed_room(factory, path_id=path_id, slug="intro", room_order=0)

    orders = [1, 0, None, 2, None]
    for i, order in enumerate(orders):
        await _seed_problem(
            factory,
            course_id=course_id,
            room_id=room_id,
            task_order=order,
            question=f"Q{i}",
            correct_answer=f"ans{i}",
        )

    resp = await ac.get(f"/api/paths/python-fundamentals/rooms/{room_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned_orders = [t["task_order"] for t in body["tasks"]]
    # Non-null orders first ascending, then two nulls last.
    assert returned_orders[:3] == [0, 1, 2]
    assert returned_orders[3:] == [None, None]
    # Correct answer must NOT be leaked to the client.
    for t in body["tasks"]:
        assert "correct_answer" not in t
    assert body["path_slug"] == "python-fundamentals"
    assert body["task_total"] == 5
    assert body["task_complete"] == 0
    assert body["outcome"] == "Complete this mission"
    assert body["difficulty"] == 2
    assert body["eta_minutes"] == 15
    assert body["module_label"] == ""


# ── 7. GET /api/paths/{slug}/rooms/{room_id} — is_complete flag ────


@pytest.mark.asyncio
async def test_get_room_detail_task_is_complete_flag(client_with_db) -> None:
    """One correct answer out of two → tasks[0].is_complete=True."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(factory, slug="python-fundamentals")
    room_id = await _seed_room(factory, path_id=path_id, slug="intro", room_order=0)

    p1 = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=0
    )
    p2 = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=1
    )
    await _seed_correct_result(factory, user_id=user_id, problem_id=p1)

    resp = await ac.get(f"/api/paths/python-fundamentals/rooms/{room_id}")
    assert resp.status_code == 200, resp.text
    tasks = resp.json()["tasks"]
    by_id = {uuid.UUID(t["id"]): t for t in tasks}
    assert by_id[p1]["is_complete"] is True
    assert by_id[p2]["is_complete"] is False
    assert resp.json()["task_complete"] == 1


# ── 8. GET /api/paths/orphans — count + sample ─────────────────────


@pytest.mark.asyncio
async def test_get_orphans_returns_count_and_sample(client_with_db) -> None:
    """15 orphan cards → count=15, sample length capped at 10."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    for i in range(15):
        await _seed_problem(
            factory,
            course_id=course_id,
            room_id=None,  # orphan — no path_room_id
            task_order=None,
            question=f"Orphan {i}",
        )

    resp = await ac.get("/api/paths/orphans")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 15
    assert len(body["sample"]) == 10
    # Sample rows carry the id + title shape the dashboard expects.
    for row in body["sample"]:
        assert "id" in row and "title" in row
        assert row["title"].startswith("Orphan ")


@pytest.mark.asyncio
async def test_get_current_mission_returns_null_when_nothing_started(
    client_with_db,
) -> None:
    """Mapped missions with zero progress should not surface as current."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(factory, slug="python-fundamentals")
    room_id = await _seed_room(factory, path_id=path_id, slug="intro", room_order=0)
    await _seed_problem(factory, course_id=course_id, room_id=room_id, task_order=0)
    await _seed_problem(factory, course_id=course_id, room_id=room_id, task_order=1)

    resp = await ac.get("/api/paths/current-mission")
    assert resp.status_code == 200, resp.text
    assert resp.json() is None


@pytest.mark.asyncio
async def test_get_current_mission_ignores_completed_missions(client_with_db) -> None:
    """A fully green mission should not be returned as in-progress."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(factory, slug="python-fundamentals")
    room_id = await _seed_room(factory, path_id=path_id, slug="intro", room_order=0)
    p1 = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=0
    )
    p2 = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=1
    )
    await _seed_correct_result(factory, user_id=user_id, problem_id=p1)
    await _seed_correct_result(factory, user_id=user_id, problem_id=p2)

    resp = await ac.get("/api/paths/current-mission")
    assert resp.status_code == 200, resp.text
    assert resp.json() is None


@pytest.mark.asyncio
async def test_get_current_mission_returns_partial_mission_with_metadata(
    client_with_db,
) -> None:
    """A partially-complete mission should surface with room/path metadata."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(
        factory,
        slug="python-fundamentals",
        title="Python Fundamentals",
    )
    room_id = await _seed_room(
        factory,
        path_id=path_id,
        slug="loops",
        title="Loops",
        room_order=2,
        intro_excerpt="Start with for-loops.",
        outcome="Write a loop that filters a list",
        difficulty=3,
        eta_minutes=20,
        module_label="Basics",
    )
    p1 = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=0
    )
    await _seed_problem(factory, course_id=course_id, room_id=room_id, task_order=1)
    await _seed_problem(factory, course_id=course_id, room_id=room_id, task_order=2)
    await _seed_correct_result(factory, user_id=user_id, problem_id=p1)

    resp = await ac.get("/api/paths/current-mission")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["mission_id"] == str(room_id)
    assert body["path_id"] == str(path_id)
    assert body["path_slug"] == "python-fundamentals"
    assert body["path_title"] == "Python Fundamentals"
    assert body["title"] == "Loops"
    assert body["intro_excerpt"] == "Start with for-loops."
    assert body["outcome"] == "Write a loop that filters a list"
    assert body["difficulty"] == 3
    assert body["eta_minutes"] == 20
    assert body["module_label"] == "Basics"
    assert body["task_total"] == 3
    assert body["task_complete"] == 1
    assert body["progress_pct"] == 33


@pytest.mark.asyncio
async def test_get_current_mission_picks_most_recent_partial_mission(
    client_with_db,
) -> None:
    """When multiple missions are partial, the freshest activity wins."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    earlier = datetime(2026, 4, 24, 9, 0, tzinfo=timezone.utc)
    later = earlier + timedelta(hours=2)

    path_a = await _seed_path(factory, slug="python-fundamentals", title="Python")
    room_a = await _seed_room(
        factory, path_id=path_a, slug="loops", title="Loops", room_order=0
    )
    a1 = await _seed_problem(factory, course_id=course_id, room_id=room_a, task_order=0)
    await _seed_problem(factory, course_id=course_id, room_id=room_a, task_order=1)
    await _seed_correct_result(
        factory,
        user_id=user_id,
        problem_id=a1,
        answered_at=earlier,
    )

    path_b = await _seed_path(factory, slug="hacking-foundations", title="Hacking")
    room_b = await _seed_room(
        factory, path_id=path_b, slug="recon", title="Recon", room_order=0
    )
    b1 = await _seed_problem(factory, course_id=course_id, room_id=room_b, task_order=0)
    await _seed_problem(factory, course_id=course_id, room_id=room_b, task_order=1)
    await _seed_correct_result(
        factory,
        user_id=user_id,
        problem_id=b1,
        answered_at=later,
    )

    resp = await ac.get("/api/paths/current-mission")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["mission_id"] == str(room_b)
    assert body["path_slug"] == "hacking-foundations"
    assert body["title"] == "Recon"
