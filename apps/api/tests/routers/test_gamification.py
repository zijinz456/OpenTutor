"""Integration tests for ``/api/gamification/*`` (Phase 16c Subagents A+B).

Router-level acceptance criteria from Story 1 + Bundle B Part A delta:

1. ``test_dashboard_new_account_returns_zeros`` — empty user → all
   zeros, empty arrays, ``level_tier == "Bronze I"``.
2. ``test_dashboard_xp_total_picks_silver_tier`` — 600 XP → Silver
   band, ``level_progress_pct > 0``.
3. ``test_dashboard_heatmap_has_exactly_365_days`` — heatmap is dense:
   exactly 365 tiles, today inclusive, quiet days carry ``xp=0``.
4. ``test_dashboard_streak_days_reflects_compute_streak`` — three
   consecutive XP days (today + 2 prior) → ``streak_days == 3``.
5. ``test_dashboard_active_paths_lists_user_paths`` — a user with one
   ``PracticeResult`` against a path's task surfaces that path in
   ``active_paths``.
6. ``test_dashboard_daily_goal_default_is_ten`` — no preference row →
   ``daily_goal_xp == 10``.
7. ``test_dashboard_daily_goal_picks_up_user_preference`` — configured
   ``daily_goal_xp=20`` overrides the default.
8. ``test_dashboard_daily_goal_preference_override`` — Bundle B
   regression covering the same override at a different XP amount.
9. ``test_dashboard_includes_xp_to_next_level`` — field present and
   non-negative on a fresh dashboard.
10. ``test_xp_to_next_level_at_band_boundaries`` — pure-helper
    boundaries (Bronze=0→500, Silver=500→1500, Diamond=10000→0).

Harness mirrors :mod:`tests.routers.test_paths` — temp SQLite, override
``get_db``, patch ``database.async_session`` so any background helpers
that grab the global factory still target the test DB. The router is
NOT registered yet (the main agent owns ``router_registry`` integration
per the Subagent B brief), so we mount it directly on the app under
the same ``/api/gamification`` prefix the production wiring will use.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import database as database_module
from database import Base, get_db
from main import app
from models.course import Course
from models.learning_path import LearningPath, PathRoom
from models.practice import PracticeProblem, PracticeResult
from models.preference import UserPreference
from models.user import User
from models.xp_event import XpEvent  # registers xp_events on Base.metadata
from routers.gamification import router as gamification_router


# ── App-level mount (idempotent) ────────────────────────────────────
# Production wiring lands in ``services.router_registry`` later — the
# main agent integrates Subagents A+B together. Until then, mount
# directly on the FastAPI app for tests. Guarded so re-imports during
# the test session don't double-register the router.
_MOUNT_PATH = "/api/gamification"


def _ensure_mounted() -> None:
    """Mount the gamification router on the shared ``app`` if absent.

    FastAPI exposes routes via ``app.routes``; we look for any route
    whose path starts with the gamification prefix to detect a prior
    mount. Mounting twice would surface duplicate operationIDs.
    """

    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith(_MOUNT_PATH):
            return
    app.include_router(gamification_router)


_ensure_mounted()


# ── Anchor for deterministic windows ────────────────────────────────
# A day far from a week boundary keeps freeze quota arithmetic clean.
# We DON'T pin "today" here — the dashboard endpoint reads ``utcnow``
# directly, so tests must seed XP events keyed off the real today.


# ── Fixtures ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client_with_db():
    """Per-test ``AsyncClient`` + session factory bound to a fresh DB.

    Mirror of :func:`tests.routers.test_paths.client_with_db`. Also
    drops the ``freeze_tokens.problem_id NOT NULL`` constraint on
    SQLite so the streak service's auto-apply path is not crashy if
    the dashboard ever flips it on (it currently uses
    ``auto_apply_freezes=False`` so this is defensive).
    """

    fd, db_path = tempfile.mkstemp(prefix="opentutor-gam-router-", suffix=".db")
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
        await conn.execute(text("PRAGMA writable_schema = 1"))
        await conn.execute(
            text(
                "UPDATE sqlite_master SET sql = replace(sql, 'NOT NULL', '') "
                "WHERE name = 'freeze_tokens'"
            )
        )
        await conn.execute(text("PRAGMA writable_schema = 0"))

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


# ── Seed helpers ────────────────────────────────────────────────────


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
    track_id: Optional[str] = None,
) -> uuid.UUID:
    path_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            LearningPath(
                id=path_id,
                slug=slug,
                title=title,
                difficulty="beginner",
                track_id=track_id or slug.replace("-", "_"),
                description=None,
                room_count_target=0,
            )
        )
        await session.commit()
    return path_id


async def _seed_room(
    session_factory,
    *,
    path_id: uuid.UUID,
    slug: str,
    room_order: int = 0,
) -> uuid.UUID:
    room_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            PathRoom(
                id=room_id,
                path_id=path_id,
                slug=slug,
                title="Room",
                room_order=room_order,
                outcome="Do the thing",
                difficulty=2,
                eta_minutes=15,
                module_label="basics",
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
) -> uuid.UUID:
    problem_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            PracticeProblem(
                id=problem_id,
                course_id=course_id,
                question_type="mc",
                question="Q?",
                options={"choices": ["a", "b"]},
                correct_answer="a",
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
    answered_at: Optional[datetime] = None,
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


async def _seed_xp_event(
    session_factory,
    *,
    user_id: uuid.UUID,
    amount: int,
    earned_at: datetime,
    source: str = "test_seed",
) -> None:
    async with session_factory() as session:
        session.add(
            XpEvent(
                user_id=user_id,
                amount=amount,
                source=source,
                source_id=uuid.uuid4(),
                earned_at=earned_at,
            )
        )
        await session.commit()


async def _seed_daily_goal_pref(
    session_factory,
    *,
    user_id: uuid.UUID,
    goal_xp: int,
) -> None:
    async with session_factory() as session:
        session.add(
            UserPreference(
                user_id=user_id,
                scope="global",
                dimension="daily_goal_xp",
                value=str(goal_xp),
                source="onboarding",
                confidence=1.0,
            )
        )
        await session.commit()


# ── 1. New account → zeros + Bronze I ──────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_new_account_returns_zeros(client_with_db) -> None:
    """A fresh user gets all zeros and the Bronze I starter tier.

    Heatmap is dense (Bundle B spec line 148): 365 tiles every one
    carrying ``xp=0`` — fresh accounts don't get an empty list.
    """

    ac, factory = client_with_db
    await _seed_user(factory)

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["xp_total"] == 0
    assert body["level_tier"] == "Bronze I"
    assert body["level_name"] == "Bronze"
    assert body["level_progress_pct"] == 0
    assert body["xp_to_next_level"] == 500  # Bronze → Silver
    assert body["streak_days"] == 0
    assert body["streak_freezes_left"] == 3  # Phase 14 default quota
    assert body["daily_goal_xp"] == 10  # default fallback
    assert body["daily_xp_earned"] == 0
    # Dense heatmap: 365 tiles, every day zero on a fresh account.
    assert len(body["heatmap"]) == 365
    assert all(tile["xp"] == 0 for tile in body["heatmap"])
    assert body["active_paths"] == []


# ── 2. Silver I tier when XP is in 500..1999 band ──────────────────


@pytest.mark.asyncio
async def test_dashboard_xp_total_picks_silver_tier(client_with_db) -> None:
    """A user with 600 XP lands in Silver I with non-zero progress."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)

    # One 100 XP slug today + five 100 XP slugs spread across prior days
    # so the unique-per-day index doesn't collide. The exact dates only
    # matter for the heatmap; here we care about the SUM (= 600).
    today = datetime.now(timezone.utc)
    await _seed_xp_event(factory, user_id=user_id, amount=100, earned_at=today)
    for offset in range(1, 6):
        await _seed_xp_event(
            factory,
            user_id=user_id,
            amount=100,
            earned_at=today - timedelta(days=offset),
        )

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["xp_total"] == 600
    assert body["level_name"] == "Silver"
    assert body["level_tier"].startswith("Silver")
    assert body["level_progress_pct"] > 0


# ── 3. Heatmap is dense — exactly 365 day rows, today inclusive ────


@pytest.mark.asyncio
async def test_dashboard_heatmap_has_exactly_365_days(client_with_db) -> None:
    """Bundle B spec line 148: dense 365-element heatmap, today last.

    Activity on three days seeds three positive tiles; the remaining
    362 tiles ship with ``xp=0``. Dates are strictly increasing and
    the last tile is today.
    """

    ac, factory = client_with_db
    user_id = await _seed_user(factory)

    today_dt = datetime.now(timezone.utc)
    today_iso = today_dt.date().isoformat()
    # Three distinct days of activity.
    for offset in (0, 2, 5):
        await _seed_xp_event(
            factory,
            user_id=user_id,
            amount=12,
            earned_at=today_dt - timedelta(days=offset),
        )

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    heatmap = body["heatmap"]
    # Dense: exactly 365 tiles every time, regardless of activity.
    assert len(heatmap) == 365
    # Last tile is today.
    assert heatmap[-1]["date"] == today_iso
    # Strictly increasing dates so the frontend can iterate left → right.
    dates = [tile["date"] for tile in heatmap]
    assert dates == sorted(dates)
    # Three positive tiles for the three seeded days; the rest are 0.
    positive = [tile for tile in heatmap if tile["xp"] > 0]
    assert len(positive) == 3
    assert all(tile["xp"] == 12 for tile in positive)
    # ISO date format check on every tile.
    for tile in heatmap:
        assert len(tile["date"]) == 10 and tile["date"][4] == "-"


# ── 4. streak_days reflects compute_streak ─────────────────────────


@pytest.mark.asyncio
async def test_dashboard_streak_days_reflects_compute_streak(client_with_db) -> None:
    """Three consecutive XP days → streak_days=3."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)

    today = datetime.now(timezone.utc)
    for offset in range(3):  # today, yesterday, day before
        await _seed_xp_event(
            factory,
            user_id=user_id,
            amount=10,
            earned_at=today - timedelta(days=offset),
        )

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["streak_days"] == 3


# ── 5. Active paths populated when user has results ────────────────


@pytest.mark.asyncio
async def test_dashboard_active_paths_lists_user_paths(client_with_db) -> None:
    """A path with at least one user result surfaces in active_paths."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    course_id = await _seed_course(factory, user_id=user_id)
    path_id = await _seed_path(
        factory, slug="python-fundamentals", title="Python Fundamentals"
    )
    room_id = await _seed_room(factory, path_id=path_id, slug="intro", room_order=0)
    problem_id = await _seed_problem(
        factory, course_id=course_id, room_id=room_id, task_order=0
    )
    await _seed_correct_result(factory, user_id=user_id, problem_id=problem_id)

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["active_paths"]) == 1
    summary = body["active_paths"][0]
    assert summary["slug"] == "python-fundamentals"
    assert summary["title"] == "Python Fundamentals"
    assert summary["rooms_total"] == 1
    # Single-room path with the only task answered correctly → 1/1.
    assert summary["rooms_completed"] == 1


# ── 6. Default daily goal is 10 when no preference exists ──────────


@pytest.mark.asyncio
async def test_dashboard_daily_goal_default_is_ten(client_with_db) -> None:
    """Absent ``daily_goal_xp`` preference → default 10 XP/day."""

    ac, factory = client_with_db
    await _seed_user(factory)

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    assert resp.json()["daily_goal_xp"] == 10


@pytest.mark.asyncio
async def test_dashboard_daily_goal_picks_up_user_preference(
    client_with_db,
) -> None:
    """A ``daily_goal_xp=20`` preference overrides the default."""

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    await _seed_daily_goal_pref(factory, user_id=user_id, goal_xp=20)

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    assert resp.json()["daily_goal_xp"] == 20


# ── 7. Bundle B regression: daily goal preference override ─────────


@pytest.mark.asyncio
async def test_dashboard_daily_goal_preference_override(
    client_with_db,
) -> None:
    """Bundle B spec line 149-151: configured override beats default.

    Same shape as the prior test but spelled with the spec's exact
    label so a Part-D test-coverage audit lands on a single grep hit
    (``daily_goal_preference_override``).
    """

    ac, factory = client_with_db
    user_id = await _seed_user(factory)
    await _seed_daily_goal_pref(factory, user_id=user_id, goal_xp=20)

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    assert resp.json()["daily_goal_xp"] == 20


# ── 8. xp_to_next_level present in dashboard payload ──────────────


@pytest.mark.asyncio
async def test_dashboard_includes_xp_to_next_level(client_with_db) -> None:
    """Bundle B spec line 142: response carries ``xp_to_next_level``.

    Fresh account is in Bronze, so the delta to Silver (500) is 500.
    The smoke check is "field present and ≥ 0"; the exact value
    boundary cases live in
    :func:`test_xp_to_next_level_at_band_boundaries`.
    """

    ac, factory = client_with_db
    await _seed_user(factory)

    resp = await ac.get("/api/gamification/dashboard")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "xp_to_next_level" in body
    assert body["xp_to_next_level"] >= 0
    # Fresh account: 0 XP, Bronze band, 500 XP to Silver.
    assert body["xp_to_next_level"] == 500


# ── 9. xp_to_next_level pure helper at band boundaries ────────────


def test_xp_to_next_level_at_band_boundaries() -> None:
    """Bundle B Part D: helper boundary table.

    Spec-mandated cases: Bronze=0 → 500, Silver=500 → 1500,
    Diamond=10000 → 0. Pure unit test against the private helper in
    :mod:`routers.gamification`. Not a router roundtrip — the
    contract is "given an XP total, return the XP delta to the next
    band's lower bound", and the helper is the one place that math
    lives.
    """

    from routers.gamification import _xp_to_next_level

    # Spec-mandated triple.
    assert _xp_to_next_level(0) == 500  # Bronze → Silver (500)
    assert _xp_to_next_level(500) == 1500  # Silver → Gold (2000)
    assert _xp_to_next_level(10000) == 0  # Diamond — no next band

    # Defensive corners that the helper still has to get right.
    assert _xp_to_next_level(-50) == 500  # negative clamps to 0
    assert _xp_to_next_level(499) == 1  # one XP from Silver
    assert _xp_to_next_level(1999) == 1  # one XP from Gold
    assert _xp_to_next_level(2000) == 3000  # Gold → Platinum (5000)
    assert _xp_to_next_level(5000) == 5000  # Platinum → Diamond (10000)
    assert _xp_to_next_level(50_000) == 0  # deep in open Diamond band
